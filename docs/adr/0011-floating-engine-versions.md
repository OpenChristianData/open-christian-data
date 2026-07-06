# ADR-0011: Floating OCR engine versions; record actual version per-rendering

**Status:** Accepted (2026-05-15); amended 2026-05-16 (R59 — capture mechanism, rendering immutability + supersession, change-detection in Reviewer state)

## Context

The OCR pipeline (Tesseract by default; alternative engines as escalation) produces renderings whose byte-for-byte content depends on:

1. The scan image (stable; we hold the source bytes).
2. The OCR engine version and its language packs (changes over time as engines improve).
3. Engine parameters (configurable per run).

The architectural question: do we pin a specific OCR engine version (e.g. `tesseract@5.3.0`) and require it for every run, or do we float — using whatever version is best available at the time the scan runs?

Pinning maximises *input-level* reproducibility: re-running the same command on the same scan with the same pinned version produces identical output bytes. The cost is that future engine improvements never reach the dataset without an explicit pin bump and a full re-OCR pass.

Floating accepts that re-running today's command tomorrow may produce different bytes (because Tesseract has been upgraded), in exchange for ongoing access to OCR quality improvements as engines improve.

## Decision

Float. The OCR pipeline uses whatever version of the OCR engine is best available at the time the scan runs. The **actual version used** is recorded per-rendering in the rendering catalog (`engine: "tesseract@5.3.0"` or whatever was running).

Reproducibility is preserved at the **output level** — anyone reading a rendering's catalog entry knows which engine version produced it — rather than at the **input level** (pinning forever).

This applies to Tesseract (the default), to any alternative engine used for escalation (PaddleOCR, Google Vision, AWS Textract), and to any engine that joins the pipeline later. The principle is engine-agnostic.

### R59 amendment — capture, immutability, supersession

The original ADR specified that the version is recorded but did not specify how. Three operational rules close the gap:

1. **Engine version is captured at runtime.** `build/tools/ocr_pipeline/build_rendering.py` reads the engine version programmatically before invoking the engine: Tesseract via `tesseract --version`; PaddleOCR via the package version reported by `paddleocr.__version__`; cloud engines via the API endpoint version field. The captured value populates the rendering catalog entry's `engine` field at write time. A schema-validation test (`test_engine_field_captured_from_runtime`) asserts every rendering in `data/<type>/<author>/<work>/<edition>/catalog.json` has a non-null `engine` string and rejects null or empty values; CI fails on regression.

2. **Renderings are immutable once catalogued.** Re-OCR of an existing rendering produces a **new rendering** with a new rendering ID; the existing rendering's bytes are not overwritten. The catalog records the relationship via `supersedes: <old_rendering_id>` on the new entry and `superseded_by: <new_rendering_id>` on the old entry. Both entries remain in `catalog.json`; both renderings remain addressable on disk. Overwrite-with-audit-log is rejected because scans and parses are gitignored — once overwritten the previous bytes are practically unrecoverable, so the audit-log alone cannot serve provenance recovery.

3. **Bytes-change detection in Reviewer state.** When Reconcile re-runs with a superseding rendering, disagreements whose readings change are surfaced via an `OCR_BYTES_CHANGED` Reviewer warning on affected records. The Reviewer re-adjudicates only the changed disagreements; unchanged disagreements keep their existing decisions. The supersession event is logged as a structural audit entry (`engine_supersession`) naming the old engine version, new engine version, count of changed disagreements, and count of preserved Reviewer decisions. The within-edition-divergence Checker (locked plan §"New Checker contracts") gains the engine-version diff as an input.

The supersession metadata lives in `catalog.json` because the catalog is already the named source of truth for rendering provenance; a separate `renderings_history.json` would split provenance across two files and create drift risk.

## Consequences

**Positive**

- The dataset benefits from engine improvements as they ship. Better Tesseract = better OCR for free; no architectural barrier, no pin-bump ceremony required.
- Catalog metadata is the source of truth for "what produced this rendering" — readers don't need to query the build environment to know which engine version is responsible for given bytes.
- Fits the "quality grows over time" framing (ADR-0008). The architecture's slot for OCR is built once; quality of OCR output improves within the slot by engine evolution, not by adding a new slot.
- No long-term commitment to a specific engine version that may become unavailable or unmaintained. Future contributors install whatever Tesseract their package manager provides; the catalog records what they got.

**Negative**

- Re-running the same OCR command on the same scan months later may produce different bytes if the engine has been upgraded. The fix path: re-OCR the affected renderings and accept the diff (Reviewer re-adjudicates if disagreements change).
- A consumer who wants strict byte-for-byte reproducibility of the dataset's OCR-derived content has to read catalog entries to know which engine version each rendering came from, and install that exact version themselves. The metadata makes this possible but doesn't make it convenient.
- Debugging "why did this run produce different output than last month's?" requires comparing catalog engine versions, not just the command line.
- A subtle Reviewer trap: if we re-OCR a rendering with a newer engine and the OCR is *worse* on some pages, we discover this only by comparing outputs. The Reconcile cross-rendering machinery surfaces it (dry-run agreement drop), but it's not automatic.

## Alternatives considered

- **Pin a specific Tesseract version (e.g. `tesseract@5.3.0`) for the project's lifetime.** Rejected. The trade-off (input-level reproducibility) doesn't outweigh the cost (never receiving engine improvements). For a corpus published once and then refined over years, frozen-pin status freezes quality.
- **Pin per-rendering: every rendering declares its required engine version; CI enforces it on re-runs.** Considered. Rejected as bureaucracy. The catalog already records what was used; requiring CI to refuse to re-OCR with a different version turns engine version into a synchronisation barrier across all collaborators, which is the worst of both worlds.
- **Pin a "current as of this date" version once a year; bump annually with a documented re-OCR pass.** Considered. Rejected because the annual cadence still locks the project out of mid-year improvements; the operational cost of the annual bump (re-OCR pass, Reviewer re-adjudication of changed disagreements) doesn't buy much over the per-rendering metadata approach.
- **Float for development; pin for published-to-HuggingFace versions.** Considered. The catalog already captures actual version per-rendering; HuggingFace consumers get the version metadata via the dataset card and per-record provenance. Adding a "pinned for publish" mechanism duplicates effort.
