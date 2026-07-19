# Open Christian Data — Glossary

The NSH OCR-pipeline vocabulary (“Layer 1”) moved to the EzraOCR repo: `../EzraOCR/docs/NSH_LEXICON.md`.

Canonical vocabulary for the rearchitected OCD pipeline. Glossary only — no rationale, no schema sketches, no implementation detail. For those, see `plans/2026-05-14-multi-source-rearchitecture.md` (rearchitecture design) and `docs/adr/` (architecture decisions).

Update this file when terms resolve or change. Never let two terms in the codebase refer to the same concept; never let one term refer to two concepts.

> **2026-06-19 / extended 2026-06-25 — major NSH OCR-pipeline vocabulary change.** A grill-with-docs lexicon pass renamed the OCR layer: `sidecar` -> **page transcription**, `rendering` -> **standardised transcription**, `WCT` -> **word alignment table**, the S3 reconciler -> **Reconciliation** (product **reconciled page**; `consensus` kept narrow), and the whole stage set into a clean **ten-stage taxonomy** (one stage = one cohesive unit; LLM Review and Human Review split; Typography moved before Human Review; feedback loops named). The canonical terms now live in the EzraOCR repo (`../EzraOCR/docs/NSH_LEXICON.md`). Schema ids, filenames, and stage numbers are **not** renamed yet — that physical migration is deferred; the old->new map and rationale are in **ADR-0016**. The one design change beyond naming (LLM may propose unattested readings, gated by Human Review in v1) is **ADR-0018**.

---

## Core data terms

**Work** — The intellectual content of a text. Identified by author + work slug (e.g. `wesley/notes-on-the-bible`). The work is eternal; it does not change.

**Edition** — A specific historical publication of a work. Identified by date or date-range, optionally with a disambiguator when the date alone is not unique (e.g. `1810-1826`, `1559`, `1844-sproul`). The thing we cite for public-domain status.

**Source** — The digital provider that hosts or produces a rendering (e.g. `ccel`, `ia`, `gutenberg`, `our-ocr`). Not to be confused with the historical print artefact (that is the *edition*).

**Format** — The digital encoding of a rendering (`thml`, `ocr`, `html`, `tei`, `epub`, `pdf`, `plain`).

**Rendering** — The concrete bytes of one *source*'s *format*-rendering of one *edition* of one *work*. The thing parsers consume. Identified by the slash-path handle `<source>/<author>/<work>/<edition>/<format>` (with optional `<translator>`, `<volume>`, `<language>` segments where applicable).

**Block** — A unit of source text (paragraph, heading, list item, footnote, lemma, verse line, headword, quote, table row). The unit of attestation in a reconciled record. Blocks live in a linear sequence in source order.

**Lemma** — In a commentary, the source-text phrase being commented on — the quoted snippet from the underlying text that introduces a comment. E.g. in Wesley's note on 1 John 1:1, "Whom he hath seen" is the lemma; the following paragraph is the comment on it. Block-type for that quoted snippet.

**Headword** — In a reference work, dictionary, encyclopedia, or lexicon, the term that names the entry. E.g. "Abraham" is the headword for the Schaff-Herzog entry on Abraham. Block-type for that entry-title block.

**Annotation** — Per-block structural metadata (verse reference, date, term, section path, chapter number) overlaid on the block. Does not drive the block's position in the sequence.

---

## Provenance & attestation

**Attested by (block-level)** — The renderings that contain a given block. Coverage attestation. "These renderings know about this block."

**Chosen reading attested by** — The renderings whose text matches the published reading at a specific disagreement span within a block. Textual agreement. "These renderings say it this way."

**Composed reading** — A canonical reading assembled by per-character voting or correction across renderings, where no single rendering produced the whole reading verbatim. Distinct from an *attested reading*, which one rendering produced as-is. Carries character provenance and a derivation level. See ADR-0014.

**Character provenance** — The per-character record of which source produced each character of a composed reading: an engine family, a confusion rule, a lexicon, a language model, or a human. Makes a composed reading auditable at character granularity. See ADR-0014.

**PD anchor** — The single public-domain edition of a work that serves as the citation basis. Exactly one per work-edition. Surfaced as a per-work decision during migration; recorded in metadata with rationale.

**PD attestor** — A public-domain rendering that supports readings; appears in `attested_by`. Plural per work-edition.

**Reference copy** — A rendering used for verification only (non-anchor public-domain, or copyrighted). Never enters `attested_by`. The Reviewer can compare against it.

**Disagreement (textual)** — A token-span within an aligned block where renderings differ in text. Recorded with per-rendering readings, classification (`ocr_noise`, `capitalisation`, `punctuation`, `spelling_variant`, `word_substitution`, `paraphrase`, `whitespace`, `unclassified`), chosen reading, and resolution.

**Structural disagreement** — A block-level mismatch between renderings (one merges where another splits; one has a heading the others don't; one is missing the block entirely).

**Match explanation** — A per-decision record in a reconciled record's `match_explanations` ledger. Carries the inputs to one Reconcile decision (block-pair edge match, reading-score disagreement, or structural-rule application). The decision's output lives on its own record type and references the explanation by `match_explanation_id`. See ADR-0013.

**Block-pair threshold bucket** — A score-band classifier for block-pair edge decisions: `high`, `mid_high`, `mid_low`, `low`. Independent of the action taken and the Reviewer-surface policy, which are recorded in separate fields. See ADR-0013.

**Reviewer surface** — The visibility of a Reconcile decision to the Reviewer: `required` (rendered in the Reviewer UI's pending queue), `silent` (audit-log entry only), or `none` (no audit-log entry). Per-block-type defaults for borderline cluster decisions live in ADR-0013.

---

## Pipeline stages

The pipeline has **eight stages**: `Fetch → Parse → Reconcile → Transliterate → Check → Modernise → Check → Publish`. Check appears at two gates — once after Transliterate (gates Modernise) and once after Modernise (gates Publish); same stage, same Checkers, same Reviewer UI, applied at two points. Transliterate is mandatory; Modernise is optional per work. See locked plan §"The pipeline, end to end".

**Fetch** — Acquires raw bytes for each rendering. Inputs: rendering ID + source URL. Outputs: cached raw bytes (local-only).

**Parse** — Per-rendering parser converts raw bytes into a per-rendering JSON in the universal block-sequence shape.

**Reconcile** — Aligns N renderings of one edition (within-edition only) and produces a single reconciled record with two-level attestation and disagreement records. Preserves source-faithful bytes in every block (including non-Latin script). Implemented as an *anchor graph*: shared annotations (verse refs, terms, dates, section paths) across renderings become high-confidence alignment anchors that split each rendering into windows; within-window blocks are aligned by text similarity, block-type match, and position. See locked plan §"The Reconcile stage in depth".

**Transliterate** — Mandatory stage between Reconcile and the first Check. Writes Latin-script bytes into `original_text` for every block while preserving the source's original-language bytes exactly in `language_segments[].original_script`. Rule-driven via per-language transliteration rulesets at `build/lib/modernisation/rulesets/transliteration/<lang>.yaml`; editorial overrides follow the same audit pattern as Modernise. No-op for blocks with no non-Latin script. The first Check validates post-Transliterate state.

**Modernise** — Optional stage that produces a modernised-spelling sibling record from a Reviewer-clean post-Transliterate record. Rule-driven (per-language YAML rulesets) plus editorial (judgement calls). When skipped, only the `original` config publishes; Transliterate has already produced the consumer-facing Latin-script text.

**Check** — Existing Checkers run against reconciled records and modernised siblings; flag blocks for Reviewer adjudication.

**Publish** — Two-step: (1) **Local export** (Phase 1) — `build/tools/export_hf_dataset.py` produces a HuggingFace dataset artefact under `exports/` (gitignored) with two configs (`original`, `modernised`) and the dataset card. (2) **Remote push** (Phase 3 soft-launch) — `build/tools/upload_huggingface.py` invokes `huggingface-cli` to push the artefact to the dataset repo. Manually invoked.

---

## Reviewer machinery

**Reviewer** — The quality-control layer between *the dataset* and *release*. Adjudicates disagreements with per-source attestation visible.

**Checkers** — The producers that emit warnings about records. (Formerly "producers".)

**Workbench file** — The per-record review state. (Formerly "sidecar" or "review_state".)

**Change log** — The correction ledger of decisions made by the Reviewer. (Formerly "correction ledger".)

**Audit log** — `review/audit.jsonl`; append-only record of audited decisions.

**Retry queue** — The store for transient-failure recovery. (Formerly "dead-letter".)

**Reviewer UI** — The HTML output of `render_review_html`. Extended with a split-pane scan view, per-disagreement adjudication affordances, structural-disagreement affordances, and per-modernisation accept/override controls.

**Review patch** — A JSON file emitted by the Reviewer UI carrying accumulated Reviewer decisions (audit entries, catalog deltas, workbench deltas, tool-version stamp). Schema: `schemas/v1/review_patch.schema.json`. The Reviewer UI cannot write directly to disk from a `file://` URL; `build/tools/apply_review_patch.py` is the CLI that validates a patch and applies it to `review/audit.jsonl`, `catalog.json`, and workbench files. `build/tools/inspect_review_patch.py` shows you what would change without applying. See ADR-0012 (amended 2026-05-16).

---

## Catalogs & storage

**Rendering catalog** — Per-work registry of all known renderings with their roles. Lives at `data/<type>/<author>/<work>/<edition>/catalog.json`. (Formerly "Reference catalog" or "witness registry"; renamed because the catalog now covers anchors, attestors, and reference copies — not just comparison sources.)

**Rendering role** — One of `pd_anchor` (citation basis; exactly one per work-edition), `pd_attestor` (public-domain; in `attested_by`), `reference_only` (verification only; never in `attested_by`; applies to alternative renderings of the *same work* — per-language lexicons are not modelled here, see "Lexicon work" below), `pending` (ingested but role undecided).

**Lexicon work** — A reference work (lexicon, concordance, grammar, theological dictionary) modelled as a first-class work under `data/lexicon/<author>/<slug>/<edition>/`. Has its own rendering catalog and renderings just like commentaries or other works. Phase 1 lexicon works: Liddell-Scott (`grc`), BDB (`hbo`), Lewis & Short (`la`); ship with `catalog.json`, local public-domain rendering bytes, and a build-time-generated `_index.json` for Reviewer raw-search. Reconciled-lexicon records (Reconcile run over the lexicon itself) are out of Phase 1 scope per ADR-0008 bucket 2. Not to be confused with the Layer-2 language-detection word lists at `build/lib/lexicons/<lang>.py` (different artefact; same word).

**Per-language reference resource registry** — A YAML file at `build/lib/reference_resources/<lang>.yaml` mapping a language code to one or more lexicon work-handles. Consumed by the Reviewer UI when adjudicating disagreements in a target language. Phase 1 entry shape: `work_handle`, `resource_type`, `scope_note`. Schema-validated (language code in ADR-0010 active set; `resource_type` in `{lexicon, concordance, grammar, theological_dictionary}` whitelist; every `work_handle` resolves to an existing `data/lexicon/<author>/<slug>/<edition>/catalog.json`; Phase 1 minimum entries for `grc` → Liddell-Scott, `hbo` → BDB, `la` → Lewis & Short).

**The dataset** — `data/` directory; the published records.

**Lookup table** (`data/lookup/`) — Non-record reference data used by build-time pipelines. Distinct from `data/lexicon/` (lexicon works) and from `data/<resource-type>/` (reconciled records). Example: `data/lookup/archaic_forms_en.json` (388 archaic-form → modern-form entries consumed by Modernise; moved from `data/lexicon/` in Phase 1 per R15).

**Release** — `exports/`; HuggingFace publication artefacts. Regenerable; gitignored.

**Metadata block** — The metadata header at the top of a record.

**Scans** — Local-only image files of source pages. Live in `scans/<rendering_id>/p<page>.jp2`. Never published. Page-level mapping required; bounding-box mapping is opportunistic — preserved when the parser produces it as a natural side effect (Tesseract hOCR, ALTO XML), never created from scratch.

---

## Modernisation

**Rule (modernisation)** — A declarative entry in a per-language ruleset YAML file (`build/lib/modernisation/rulesets/<lang>.yaml`). Fields: `rule_id`, `description`, `pattern`, `replacement`, `exceptions`, `enabled`, `version_added`.

**Ruleset version** — Semantic version per language (e.g. `en@1.0.0`). Bumped when rules are added, modified, or disabled. Each modernised record records the ruleset version that produced it.

**Editorial modernisation** — A modernisation that does not fit a rule; a judgement call. Recorded with `rule_id: null` and a `kind: editorial` flag plus rationale. Survives ruleset version bumps.

**Reviewer override** — A Reviewer decision to keep the original text in a block despite a rule firing. Recorded as an exception; survives ruleset version bumps.

---

## Operations

**Re-parse** — Re-running the parser on existing raw bytes (no re-fetch).

**Re-fetch** — Re-fetching raw bytes from the source URL.

**Re-reconcile** — Re-running the Reconcile stage on existing per-rendering JSONs (e.g. after Reconcile algorithm changes).

**Re-transliterate** — Re-running the Transliterate stage with an updated transliteration ruleset; preserves editorial overrides and Reviewer overrides. Triggers re-Modernise on any modernised siblings affected, since Modernise consumes post-Transliterate text.

**Re-modernise** — Re-running the Modernise stage with an updated ruleset; preserves editorial overrides and Reviewer overrides.

---

## Surfaces

**HuggingFace dataset** — `openchristiandata/open-christian-data` on HuggingFace. Two configs: `original`, `modernised`. Consumer-facing only.

**Public GitHub** — `OpenChristianData/open-christian-data` on GitHub. The dataset + build pipeline + schemas + tests + Reviewer machinery + workbench / change log / audit log / retry queue. Done work.

**Local-only** — Scans, per-rendering parses, drafts, prompts, `LAST_SESSION_*.md`, generated reports, HuggingFace export artefacts, raw source caches, working notes. Gitignored. Local working files.

---

## Multi-language

**Language tag** — A per-block field naming the dominant language of the block. OCD uses biblical-language ISO codes where they differ from modern defaults. The Phase 1 schema enum is `grc` (Koine / Ancient Greek; not modern `el`), `hbo` (Biblical Hebrew; not modern `he`), `la`, `en`, `fr`, `de` plus `und` for content where Layer 1–3 detection cannot resolve a confident language. `arc` (Biblical / Imperial Aramaic), `syr`, and `cop` are scheduled for Phase 2+ re-introduction per ADR-0010 amended (2026-05-16); they re-enter the schema enum when real corpus input arrives, with per-language artefacts shipped in the same change.

**Language segment** — An in-block foreign-language span (e.g. a Greek word in an English paragraph). Recorded in `language_segments` with `span`, `language` (underlying language code; Phase 1 enum follows ADR-0010 amended), `original_script` (the non-Latin bytes), `transliteration` (the Latin-script form used in both `original_text` and `modern_text` — see ADR-0009), and optional `transliterated_from`.

**Original script** — Per-segment field holding the source-faithful non-Latin bytes for that segment. Preserved exactly so the underlying language is recoverable from either HF config's Latin-script text.

**Transliteration** — Per-segment Latin-script form of a non-Latin span. Both HF configs (`original` and `modernised`) are Latin-script throughout; transliteration is treated as a content-faithful representation of the same words in a different script. Rule-driven by per-language transliteration rulesets (SBL-style for Greek and Hebrew, etc.) with editorial overrides recorded the same way as other modernisation overrides. See ADR-0009.

**Transliterated from** — Per-segment field flagging segments where the *source itself* already transliterated (e.g. `agapē` printed in a 19th-century commentary). Records the underlying language without changing the bytes in `original_text`.

**Per-language OCR error model** — A YAML file at `build/lib/ocr_error_models/<lang>.yaml` listing common OCR character confusions for the language. Consumed by Reconcile to classify `ocr_noise` disagreements.

**Per-language lexicon** — A Python module at `build/lib/lexicons/<lang>.py` listing known words. Consumed by the language-detection layer-2 lexicon scoring. Includes archaic / liturgical / Bible-corpus vocabulary so corpus-specific blocks resolve at Layer 2 rather than falling through to cld3.

**Per-language transliteration ruleset** — A YAML file at `build/lib/modernisation/rulesets/transliteration/<lang>.yaml` defining the transliteration scheme for that language (e.g. SBL-style for `grc` and `hbo`). Applied during the Modernise stage to produce `modern_text` and per-segment `transliteration`.

