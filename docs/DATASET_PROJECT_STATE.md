# Dataset Production — Project State (Anchor Doc)

**This is the cold-session anchor for the dataset-production half of Open Christian Data**: the
pipeline that turns public-domain Christian texts into validated JSON committed to `data/` and
published to HuggingFace — sources, parsers, schemas, validation, the published dataset, and
provenance/licensing obligations. A cold session working on the dataset should read this first.

It carries the context a session cannot infer from code (Part 1) and an audit of what has drifted
between the docs and reality (Part 3), mirroring `../EzraOCR/docs/NSH_PROJECT_STATE.md`.

> **Current state lives in the newest dated checkpoint below and the named queue.** The completed
> batch-08 wave is closed in `plans/_archive/2026-07-03-next-units-execution/00-progress-tracker.md`
> (execution plan: `00-execution-plan.md` in the same dir; master plan / design of record:
> `plans/2026-07-03-next-units-of-work.md`). The completed dataset-corrections and TEI-long-tail
> campaign is archived at `plans/_archive/2026-07-07-dataset-corrections-and-tei-long-tail/`.
> Its successor closeout trackers are archived at
> `plans/_archive/2026-07-16-dataset-fidelity-successor/` and
> `plans/_archive/2026-07-17-dataset-successor-closeout/`. The named queue for current
> fidelity and cutover decisions is `docs/DATASET_SUCCESSOR_QUEUE.md`. This anchor owns Part 1
> (invariants + decisions) and Part 3 (append-only audit history) only. When status prose here
> conflicts with the newest dated checkpoint or named queue, the newest current-state evidence wins.
> This structure was set by the 2026-07-04 architecture review
> (`plans/2026-07-04-fable-architecture-review.md` — a dated record, not a live source of truth).

**Scope boundary.** The *other* half of the project — the New Schaff-Herzog (NSH) OCR rebuild and the
gold-free corrector stack — is owned by `../EzraOCR/docs/NSH_PROJECT_STATE.md` and is out of scope here. The
only Schaff-Herzog in *this* doc's scope is the **published Project Gutenberg 1914 record**
(`data/reference/schaff-herzog-encyclopedia.json`), not the OCR rebuild. NSH artifacts that happen to
live under `data/` (e.g. `data/reference/schaff/encyclopedia/1908-1914/`, the per-volume
`reference/vol_NN.json` files) belong to the NSH anchor.

**Acquisition state lives elsewhere.** What is in the corpus, what to acquire next, and what is
blocked is owned by `research/MANIFEST.md` (the single source of truth for *acquisition*). This anchor
points to it rather than copying its queue.

---

## Part 1 — Context for Claude sessions (permanent reference)

Invariants a cold session cannot infer from code alone. These are stable; they change rarely.

### Non-negotiable invariants

- **Public-domain pre-1928 rule.** Every text must be by an author who died before 1928, making the
  content unambiguously public domain. 1928 is the hard cutoff — do not add content by authors who
  died after 1927.
- **License split: CC0 dataset / CC BY-NC 4.0 code.** The published dataset is CC0 (public-domain
  dedication); the code, schemas, and tooling are CC BY-NC 4.0. Source: `docs/LICENSING.md`,
  README license section. Input-source license maps to published-record license per the table in
  `docs/LICENSING.md` (PD/CC0 -> CC0; CC BY 4.0 -> CC BY 4.0 with attribution).
- **Schema-first validation.** Every output file validates against a schema in `schemas/v1/` before
  commit. The pre-commit hook enforces this; never bypass with `--no-verify`. `build/validate.py`
  adds structural checks beyond JSON Schema (ID uniqueness, OSIS format, cross-field consistency,
  completeness thresholds).
- **American English** in all output, documentation, and code (`color`, `organize`, `behavior`).
- **Blank over unverifiable guess in curation.** When a metadata field (source_title, attribution,
  dating, references) cannot be confirmed against a primary source, leave it blank. Schema validation
  cannot distinguish correct from plausible — a wrong value passes every check while misleading
  downstream users. Source: repo-root `CLAUDE.md` hard rules.
- **Source-attribution asks generate a deliverable, not a JSON field.** When a source's license or
  terms include a human-directed ask (credit link, citation wording, acknowledgement), the
  requirement is satisfied by a `README at <data path>` artifact a downloader of that folder alone
  would see — not by a `provenance.notes` field. Source: repo-root `CLAUDE.md`.
- **Parser-per-source + test + source config.** Each source is a parser at `build/parsers/<name>.py`,
  a test at `tests/test_<name>.py` (a pre-commit gate blocks a *new* parser without one), and a
  config at `sources/<type>/<slug>/config.json`. New parsers go through
  `superpowers:test-driven-development`.
- **OSIS verse references everywhere.** All verse references use OSIS (`Gen.1.1`,
  `Rom.9.1-Rom.9.5`). Every reference object stores both the raw source form and the OSIS form:
  `{"raw": "...", "osis": ["..."]}`. Normalize with `build/lib/bible_ref_normalizer.py` — do not
  write a new normalizer.
- **Summaries ship empty.** The enrichment layer (AI summaries, key quotes) is `null`/withheld
  across all resources — source data ships before summaries exist, and unreviewed summaries are never
  shipped. The source layer in `data/` is the canonical truth.
- **Never hand-edit `data/` JSON.** Data is produced by parsers, corrected by patch scripts, or
  regenerated — not edited in place.

### Key decisions and rationale (invisible to a cold session)

- **Source mix = HelloAO + SWORD + CCEL + Project Gutenberg + Internet Archive.** Each fills a gap:
  HelloAO (JSON API) and SWORD (CrossWire binary modules) give clean commentary/devotional/topical
  data; CCEL ThML gives structured patristic and Puritan prose; PG and IA give plain-text/DjVuTXT for
  works not in the above. Rationale: `build/DESIGN_DECISIONS.md`; per-source formats: the parser
  headers in `build/parsers/` and each source's `sources/<type>/<slug>/config.json`.
- **`research/MANIFEST.md` owns acquisition.** Corpus state, the acquisition queue, and source
  research are deliberately kept out of the production anchor so acquisition can move without
  touching production docs. MANIFEST supersedes the older `SYNTHESIS.md`,
  `CORPUS_PRIORITY_REFRESH.md`, and `ACQUISITION_QUEUE.md`.
- **Three-layer data model: source / enrichment / derived.** Source (`data/`, committed) is faithful
  to the text; enrichment (`sources/<resource>/enrichment/`) is AI-generated and reviewed; derived
  (HuggingFace export, verse hub) is generated, not committed. Enrichment references source records by
  ID and joins at build time, so source data can ship before summaries and enrichment changes don't
  pollute source history. Source: `docs/SCHEMA_SPEC.md` (Three-Layer Architecture).
- **Schema_type taxonomy (12 production types).** `bible_text`, `commentary`, `church_fathers`,
  `structured_text`, `sermon`, `catechism_qa`, `doctrinal_document`, `reference_entry`,
  `topical_reference`, `devotional`, `prayer`, `hymn_collection`. The type picks the schema that
  validates the `data` payload. `structured_text` and `doctrinal_document` store one work/document per
  file (a tree of sections/units); the rest store a flat record array. Source: `docs/SCHEMA_SPEC.md`,
  `schemas/v1/`.
- **Enums are generated, not hardcoded.** `tradition`, `work_kind`, `era`, `audience`, `license`
  enums live in `schemas/v1/` and are compiled to `build/lib/_generated_enums.py`. Import from there
  or via `build/lib/schema_enums.py::get_enum`; never hardcode a frozenset. Regenerate with
  `build/tools/generate_schema_enums.py`; drift check `build/tools/check_schema_enums_fresh.py`.

### TEI intermediate representation (ADR-0019; pilot proven 2026-07-03)

**The richer IR is TEI.** Sources selected for a richer intermediate representation normalize raw
-> TEI IR (human-verifiable; CETEIcean viewer at `viewer/index.html`) -> projections with a
`loss-receipt-v1` coverage ledger. This path is proven for named proof renderings and work sets; it
is not a claim that every source family has been migrated. City of God is proven for both renderings
(`ir/augustine/`), census-gated at the ID-set level, and schema-valid against vendored TEI P5 4.11.0
(`build/tei/vendor/`). Toolchain: `build/tei/` (census, converters, validate, project_hf,
check_ledger). Rules a session must know:

- IRs are built from RAW sources, **never** from `data/` JSON.
- One TEI per rendering; xml:ids are source-derived (deep-link anchors — never renumber).
- Any `data/` commit needs a writer manifest (`PIPELINE_REFERENCE.md` §1).
- A passing projection ledger is necessary but not sufficient evidence of fidelity. The historical
  pre-v2 BCP-1549 reproduction found 287 of 332 `<label>` texts absent, but B03a-B03c replaced
  the contract, checker, projector, and receipts: all 15 committed projections now pass strict-v2.
  The historical reproduction remains in `docs/DATASET_SUCCESSOR_QUEUE.md`; it is not evidence of
  an unfixed current defect.
- Fidelity state per format family: `docs/FORMAT_STATE_MAP.md` (all 10 families walked 2026-07-03,
  both grains). Contract: `docs/FIDELITY_CONTRACT.md`.
- A public reading website (TEI -> HTML/epub) is a confirmed future consumer. The published
  HuggingFace JSON is still produced by the legacy parser paths; flipping it to TEI projections is
  a future cutover, per-family as each family enters the IR.

### Adding a new source (workflow)

1. **Check public domain** — author must have died before 1928.
2. **Identify source + format** — HelloAO JSON API, CCEL ThML XML, CrossWire SWORD binary module,
   Standard Ebooks XHTML, Creeds.json, Project Gutenberg plain text, or Internet Archive DjVuTXT.
3. **Create the source config** at `sources/<schema_type>/<slug>/config.json` (source URL, format,
   provenance).
4. **Write the parser** at `build/parsers/<name>.py` — follow an existing parser of the same family;
   import shared utilities from `build/lib/` rather than reinventing. New parsers go through
   `superpowers:test-driven-development`.
5. **Write the test** at `tests/test_<name>.py` — the pre-commit gate blocks a new parser without
   one.
6. **Dry-run the full batch** before any write — every parser has `--dry-run`; 0 sections or 0 words
   is a hard error, not a warning (PIPE-22). Never write output without a clean dry run.
7. **Validate** — `py -3 build/validate.py --all` must exit 0 before committing. Never bypass the
   pre-commit hook with `--no-verify`.

### What to read for which task (production side)

| Task | Read |
|---|---|
| Schema reference — envelope, all 13 schema types, enum values, three-layer model, verse hub, author registry | `docs/SCHEMA_SPEC.md` (the conceptual + schema reference), `schemas/v1/` |
| Parser/build conventions (PIPE-/REL-/PY- rules) | `AGENTS.md`, `.claude/rules/*.md` |
| Acquisition: what's in, what's next, what's blocked | `research/MANIFEST.md` |
| Non-obvious classification rationale | `build/CLASSIFICATION_LOG.md` |
| Schema edge cases / known quirks | `docs/schema-quirks.md` |
| Architecture decisions | `build/DESIGN_DECISIONS.md` |
| Known external-source bugs + local workarounds | `UPSTREAM_BUGS.md` |
| Licensing split + per-source obligations | `docs/LICENSING.md` |
| HuggingFace publish process | `docs/huggingface-publishing.md`, `docs/HUGGINGFACE_DATASET_CARD.md` |
| Operational gotchas (writer manifest + registration, enum-freshness gate, HF publish) | `PIPELINE_REFERENCE.md` (gitignored, local) |

(`docs/PROJECT_CONTEXT.md` was retired on 2026-06-16 — its content moved into this anchor +
`docs/SCHEMA_SPEC.md`; the original is archived at `docs/_archive/PROJECT_CONTEXT.md`.)

---

## Part 2 — Current state (pointer — not maintained here)

Stateful current state was removed from this anchor on 2026-07-04 (its 2026-06-16 snapshot had
begun to drift; recover the old Part 2 from git history if needed). Read the live owners instead:

1. **What's done / what's next (batches, blockers):**
   The completed dataset-corrections and TEI-long-tail tracker is archived at
   `plans/_archive/2026-07-07-dataset-corrections-and-tei-long-tail/00-progress-tracker.md`.
   Its successor closeout trackers are archived at
   `plans/_archive/2026-07-16-dataset-fidelity-successor/00-progress-tracker.md` and
   `plans/_archive/2026-07-17-dataset-successor-closeout/00-progress-tracker.md`. The prior
   completed wave remains closed at
   `plans/_archive/2026-07-03-next-units-execution/00-progress-tracker.md`.
   The named queue produced by the terminal integration is
   `docs/DATASET_SUCCESSOR_QUEUE.md`; it owns the unresolved fidelity and cutover work.
2. **Acquisition (what's in the corpus, what's next, what's blocked):** `research/MANIFEST.md`.
3. **Author/work inventory and record counts:** the disk is ground truth; re-derive from the
   committed counter, never quote a hand-written doc:

   ```bash
   py -3 build/tools/count_dataset_records.py
   ```

   The generated review surfaces are `docs/WORK_CATALOG.md` and `docs/WORK_CATALOG.html`. Batch 09
   defines the public inventory unit as a recognized title-level work unit, with top-level source
   records and flattened HuggingFace JSONL rows counted separately.

4. **Fidelity state per format family:** `docs/FORMAT_STATE_MAP.md`.
5. **Publish state (HF export paths, card counts):** owned by the campaign's batch 09
   (publish-truth). The authoritative whole-corpus HuggingFace export path is
   `build/scripts/export_huggingface.py` -> `exports/huggingface/`; the `original`/`modernised`
   `build/tools/export_hf_dataset.py` path is not the current whole-corpus export. Process docs:
   `docs/huggingface-publishing.md` + `docs/HUGGINGFACE_DATASET_CARD.md`.
6. **Per-source licensing obligations:** `docs/LICENSING.md` (the one attribution-ask deliverable,
   Hymnary.org, is satisfied at `data/hymns/hymnary-pd/README.md`).

This anchor owns Part 1 (invariants + decisions) and Part 3 (append-only audit history) only.

### 2026-07-07 integration checkpoint

Batch 08 reconciled this anchor against shipped code and git history after batches 01-07 and the
publish-truth batch. The current wave result is:

- **End-to-end verification passed:** full pytest suite `3975 passed, 18 skipped, 26 xfailed`;
  `py -3 build/validate.py --all` validated 1,840 files with 0 errors and 120 warnings; TEI
  validation and all six loss ledgers returned PASS for the BCP and CCEL proof works; viewer smoke
  checks loaded BCP 1662 and Owen Mortification from `viewer/index.html` without console or page
  errors. The 2026-07-16 checkpoint below supersedes the old assumption that ledger PASS alone
  proved fidelity.
- **TEI is proven beyond the City of God pilot, not globally cut over:** BCP 1549/1559/1662 services
  plus 1928 collects now have census-gated TEI IRs, and CCEL config-driven proof works are present
  for Athanasius, *On the Incarnation*, and Owen, *Of the Mortification of Sin*. The remaining CCEL
  family and other TEI candidates still require per-family migration.
- **Parser/data fidelity fixes landed:** Gutenberg inline markers, Daily Light `scripRef`
  cross-references, Fisher Marrow OCR de-hyphenation and explicit Part II commandment sections, and
  Hastings See/See-also related terms are in shipped parser/output commits. The seven non-KJV public
  domain Bible translations are acquired through the existing `bible_text_translations.py` path.
- **JSON publication remains legacy for most families:** the HuggingFace whole-corpus export was
  refreshed in batch 09, and the authorized 2026-07-17 data upload is live. The public JSON path
  has not been flipped to TEI projections; that future per-family cutover remains separate. Public
  push remains explicit-maintainer-only.
- **Standing carry-forward queue:** TEI migration long tail (about 207 remaining CCEL configs plus
  other high-fidelity candidates), per-family publish cutover, Spurgeon MTP ordered-list loss,
  Schleitheim terminus/raw-cache repair, refreshed audit tooling, and older parser-test debt.
  This queue is now decomposed in
  `plans/2026-07-07-dataset-corrections-and-tei-long-tail/`: wave 1 starts with Spurgeon,
  Schleitheim, and the TEI candidacy inventory; the inventory gates the CCEL, clean-text, IA OCR,
  SWORD, and residual routing batches; publish cutover and integration remain terminal rows.

### 2026-07-16 dataset-corrections and TEI-long-tail checkpoint

> This checkpoint is append-only historical context. The current state is recorded in the
> 2026-07-17 checkpoint that follows it.

The terminal integration reconciled the current campaign against shipped commits and generated
artifacts. The result is real progress with a real publication blocker:

- **Parser corrections landed:** Spurgeon MTP list-item text now survives the legacy JSON parser,
  and Schleitheim stops at the confession terminus using a cached raw witness. Spurgeon list
  container and ordinal semantics still flatten outside its bounded TEI proof.
- **Named TEI proof coverage expanded, but no family was cut over:** CCEL has five proof renderings;
  Standard Ebooks has City of God, Bunyan, and Kempis; Gutenberg has Calvin's two-volume
  *Institutes* rendering; IA OCR has the bounded Fisher *Marrow* witness; and Spurgeon has proof
  sermons 1, 15, and 317. BCP proof renderings remain census-gated. These are proof works or sets,
  not family-wide migrations.
- **No publish cutover happened:** batch 09 is blocked, every family remains on its legacy public
  path, and this campaign pushed or published nothing.
- **Projection fidelity is not yet certified by a ledger PASS:** the BCP-1549 receipt passes while
  287 of 332 label texts are absent from output. Earlier campaign ledger passes remain useful
  accounting checks, but their independent censuses, probes, visual smokes, and semantic checks—not
  the ledger alone—carry the fidelity evidence.
- **Successor work is named:** `docs/DATASET_SUCCESSOR_QUEUE.md` records the ledger, BCP,
  Westminster, parser, viewer, Windows-path, and local-hook follow-ups with fresh reproduction
  evidence. Publish cutover remains blocked on its P1 items.

### 2026-07-17 dataset repair and successor closeout checkpoint

The repository-local dataset repair and successor closeout are complete. Implementation landed in
`be1e6df0`, documentation and queue closeout landed in `8a756ca8`, and the handoff was recorded
in `7a2dd65f`.

- **Strict-v2 ledger contract:** B03a (`416bd563`) added mandatory delivery evidence and an
  independent strict checker; B03b (`2d60e523`) delivered the Class B text, switched all 15
  committed receipts to v2, and verified the independent Class B and word-level results; B03c
  (`93bd28dd`) restored structural boundaries, preserved `<lb>` newlines, rejected direct text
  on delivered `<sp>`, and left all 15 receipts passing strict-v2.
- **Campaign-close publication state:** at this checkpoint, no public cutover, push, or publication
  had occurred. The public dataset was stale, including the known SWORD misfiling and phantom-book
  defects, because public publication was a separately authorized action.
- **Cold-session route:** use `docs/DATASET_SUCCESSOR_QUEUE.md` for remaining fidelity and
  cutover decisions; the completed campaign and successor trackers are in the archive paths above.

### 2026-07-17 Hugging Face publication and card-repair checkpoint

The authorized live upload to `OpenChristianDataOrg/open-christian-data` completed successfully on
2026-07-17. The verified data-upload revision immediately after all 12 JSONL uploads was
`c2b4c0e0dd6676020ee089139b665383a5bc498e` at `2026-07-17T02:41:41+00:00`. The reviewed card-only
upload completed successfully at final repository revision
`19f46f3a83913f5fd9734bf758d763d57380d5f3` (`2026-07-17T03:11:16+00:00`); it changed only the card
and did not alter the verified JSONL data payload.

- **Public release:** 408 recognized work units, 1,812 source files, 544,961 top-level source
  records, 1,811 exported source files, and 805,151 flattened JSONL rows.
- **Remote integrity:** all 12 remote JSONL files matched the reviewed local export by Git blob or
  LFS SHA-256. The expected remote README and all 12 schema JSONL paths are present.
- **Card-only defect and repair:** the first live upload exposed that the actual upload source,
  `exports/huggingface/README.md`, still had the old counts even though
  `docs/HUGGINGFACE_DATASET_CARD.md` had been corrected. The JSONL payload was correct. The ignored
  live card was verified byte-for-byte against the repaired local canonical/upload card. The
  reviewed card-only upload completed successfully and did not alter the verified JSONL data payload.
- **Rights communication:** no email, form, issue, or rights inquiry was sent.
- **Count boundary:** `data/lexicon/archaic_forms_en.json` is the one source file without
  `meta.schema_type`; it is included in the source-file inventory but is not an exported schema.

**Superseded by the ESV-removal checkpoint below.** The figures in this section remain an accurate
record of what was uploaded on 2026-07-17, and of what `main` still serves; they are no longer the
intended release contents.

### 2026-07-17 ESV rights removal — live payload is stale, re-upload pending

**The live dataset currently ships five records it should not.** `main` is still
`19f46f3a83913f5fd9734bf758d763d57380d5f3`, and its `data/doctrinal_document.jsonl` contains
`christ-hymn-of-colossians`, `christ-hymn-of-philippians`, `christian-shema`,
`confession-of-peter`, and `shema-yisrael` — each labeled `cc0-1.0` while carrying ESV text from
`esv.literalword.com`. Verified live by direct fetch on 2026-07-17. This is a public rights
exposure, not a pre-publication finding: the audit flagged it, publication proceeded, and no tag
exists yet.

Repository-side repair is complete and verified locally:

- The five entries were removed from `DOCUMENT_CONFIGS` in
  `build/parsers/creeds_json_confession.py`, so a re-run cannot regenerate them; an explanatory
  comment block records why. Rationale is in `build/CLASSIFICATION_LOG.md`.
- The five files were removed from `data/doctrinal-documents/` (39 → 34 files; 33 counted
  documents).
- `build/scripts/export_huggingface.py` was re-run: `doctrinal_document` 1,319 → 1,314 rows, total
  805,151 → **805,146**, zero ESV rows remaining in `exports/huggingface/`.
- `build/tools/count_dataset_records.py` was re-run and its output copied to `docs/WORK_CATALOG.md`
  and `docs/WORK_CATALOG.html`: 402 work units (was 407), 142 authors, 1,806 source files, 16 audit
  flags.
- Public counts were updated in `README.md`, `docs/HUGGINGFACE_DATASET_CARD.md`,
  `exports/huggingface/README.md` (kept byte-identical to the card), and `docs/releases/v0.2.0.md`.
  `docs/SOURCES.md` moves the ESV item from open blocker to resolved; three open rights questions
  remain (JWBickel, Wikisource, HistoricalChristianFaith).
- The `363 books` headline is unaffected: it sums categories that exclude doctrinal documents.

**CVW Phase 1A baseline is stale, and deliberately not repaired here.**
`tests/test_cvw_phase1a.py::test_report_does_not_generate_a_fresh_baseline` fails in the working
tree: the Phase 1A baseline binds the exact bytes of `docs/WORK_CATALOG.md` (role `authority` and
role `source`), and the catalog was regenerated. **This failure predates the ESV work** — the
baseline pins HEAD's committed catalog, and `docs/WORK_CATALOG.md` was already uncommitted-modified
by a prior session at session start, so any working-tree catalog differing from HEAD stales it. The
catalog regeneration here changes which non-matching bytes are present, not whether it is stale. At
a clean HEAD checkout the baseline matches (verified in a detached worktree; note the comparison
must be made against the checked-out file, not `git show` output, because `core.autocrlf` makes the
blob LF and the working file CRLF).

Re-capturing the baseline is a governed action and was left to the maintainer: `cvw_phase1a`
exposes no public baseline-generation operation by design, and the baseline binds an external review
anchor (`plans/2026-07-17-cvw-phase1a-governing-prior-review.md`). Re-baselining to turn the gate
green would defeat the detector that just did its job. Sequence it after the catalog settles and is
committed. The failure does not block commits: the pre-commit gate runs a scoped pytest keyed to
staged `build/` files and does not reach this test.

**Not done — requires explicit authorization:** the corrected export has not been uploaded. Until it
is, the public dataset serves ESV text under CC0. Open decision for the maintainer: re-upload the
corrected payload as `v0.2.0` (defensible — `v0.2.0` was never tagged, so no consumer can have
pinned it) or cut `v0.2.1` as a data-correction patch. `docs/releases/v0.2.0.md` is currently
written for the former and deliberately records no `v0.2.0` Hub revision, because the revision that
these notes describe does not exist on the Hub yet.

### 2026-07-17 Corpus Verification Workbench Phase 1A commitability checkpoint

The bounded read-only Phase 0/1A contract-and-fixture slice is implementation/review complete. The
durable prior governing review is
`plans/2026-07-17-cvw-phase1a-governing-prior-review.md` and the durable final independent approval
is `plans/2026-07-17-cvw-phase1a-final-approval.md`, verdict **APPROVE**. The final approval record
is outside the baseline trust cycle. The baseline is dependency/review-bound and commit-safe:
repository HEAD is retained as capture provenance only, while dependency bytes and the durable prior
review remain the currentness gate. Phase 1A becomes repository-integrated only after the root commit
succeeds and the committed checkout is verified.

The final integration challenge found and repaired one exact generic-event ownership gap: an ASV
Genesis canonical-record event can no longer pass with only sibling Exodus evidence. The focused
Phase 1A suite passes 170 tests; the full repository suite passes 2,553 tests with 1 skip and 10
expected failures. The independent integration review is
`plans/2026-07-17-cvw-phase1a-commitability-review.md`, verdict **APPROVE WITH CONDITIONS**; the
condition is exact staging plus successful post-commit verification before Phase 1B resumes.

The integration gate passed for commit `abed92f2e404592edd6c729ee4b698ee32a43594`: its exact 22-path
set, LF attributes, 170 focused tests, bound bundle/review equality, empty stale reasons, two
ownership probes, canonical `data/`/`ir/` status, and deliberate CLI BOUND/BLOCKED result were all
verified after commit. Phase 1A is repository-integrated.

The separately authorized Phase 1B evaluation subsequently began through the now-executed prompt at
`prompts/_archive/2026-07-17-cvw-phase1b-model-evaluation-coordinator.md`. Phase 2 UI, corpus-wide
review, publication integration, release, certification, public push, external contact, and direct
canonical `data/`/`ir/` edits remain outside the current state.

### 2026-07-18 Corpus Verification Workbench Phase 1B bounded-integration checkpoint

Phase 1B has advanced from the approved Phase 1A contract into a bounded, executable verification
chain. Private commits `5c95cc36`, `4fc9387e`, `6dc90952`, and `f22d70fe` provide inventory and
bundle generation, verification events, status/CLI staleness reporting, and authenticated ownership
adapters. The current witnesses are the ASV Bible collection and Spurgeon's singleton-file *All of
Grace*; both report `UNCOMPARED`, remain read-only, and mark publication `not_applicable`.

Trial 05's final architecture authenticates both the selected ownership-adapter identity and the
executing adapter bytes in the dependency trust chain. Bundle reconciliation consumes that bound
identity rather than routing by parser path or rereading mutable descriptor state. The integrated
checkout passed 131 focused Phase 1B tests, the fast suite with 2,494 passes, and the full suite with
2,700 passes; the latter two also recorded 1 skip and 10 expected failures.

This is not the Phase 1B exit condition: it proves two representative ownership grains, not that all
current production data is owned or that 100% of a selected catalog snapshot is accounted for. The
next session remains CVW-only and should define one bounded slice against the remaining exit criteria,
preferably generalizing the review/correction event path beyond its ASV proof. Other dataset and IR
migration work remains paused. The corrected 805,146-row Hugging Face export is still local and
pending separate publication authorization; this checkpoint does not authorize a re-upload, tag,
public push, Phase 2 UI, or direct canonical `data/`/`ir/` edits.

### 2026-07-18 Corpus Verification Workbench Phase 1 completion

Phases 0, 1A, and 1B reach their exit criteria. The
hash-bound selected snapshot owns 402 works and 1,806 canonical artifacts; the IR inventory owns 75
artifacts across 15 renderings; and the local publication inventory resolves all 805,146 rows in 12
exports to the selected works. The aggregate `verification-inventory-v1` is schema-valid and the
read-only CLI reports `phase1b-exit: READY`. Two works have authenticated local reconstruction
adapters; the remaining 400 are explicitly classified as referenced-only provenance ownership, not
silently presented as deep reconstruction.

Generalized review/correction events, all-schema fixtures, malformed ownership tests, and the final
Sol-high architecture gate are complete. The retained architecture improvement centralizes each
ownership adapter's validator, source identity, parser loader, and writer identity. The maintainer
subsequently authorized the canonical catalog-render refactor and its Phase 1A baseline rebind.
Catalog accounting now consumes the catalog generator directly; regeneration changed only the
ordering of the author-qualified *Expositor's Bible* rows. The maintenance rebind is explicit and is
not presented as new independent Phase 1A approval. The final adversarial architecture findings are
also closed: the catalog has a structured machine identity, Phase 1A binds stable work authorities
and LF bytes, parser dependency authentication is transitive, and all 402 works have immutable
read-only Phase 2 input routes. Final verification passed 351 combined Phase 0-1B tests, 2,545 fast
tests, and 2,752 full-suite tests. No canonical data/IR, remote publication, public push, or Phase 2
work occurred. The complete Phase 1 change is integrated in private commit `afe36400`. Phase 2
remains blocked on the repository/name decision in the master plan.

---

## Part 3 — Audit findings

Neutral catalog. Every row cites a source doc or disk evidence. `gap` = planned/committed but not
present; `drift` = present but built differently from the doc; `superseded` = the doc's basis changed.

The rows citing `docs/PROJECT_CONTEXT.md` (#4, #5, #6, #9, #14, #15) are **closed by the 2026-06-16
consolidation** — that doc was retired into this anchor + `docs/SCHEMA_SPEC.md` and the original moved
to `docs/_archive/PROJECT_CONTEXT.md`. Their `:<line>` citations map to that archived original; they
are kept here as the audit trail that motivated the retirement.

| # | Type | What was planned/claimed | What exists | Source doc | Notes |
|---|---|---|---|---|---|
| 1 | drift | `research/MANIFEST.md`: "Source configs 697" | 286 configs on disk | `research/MANIFEST.md` (pre-refresh line) | `glob('sources/**/config.json')` -> 286. Corrected in the 2026-06-16 MANIFEST refresh. |
| 2 | drift | `research/MANIFEST.md`: "data/ JSON records ~1,400+" | 1,359 files; 296,318 list-shaped records | `research/MANIFEST.md` (pre-refresh) | Row mislabeled file count as record count. Corrected in refresh. |
| 3 | drift | MANIFEST by-category "structured-text 275" | 283 files | `research/MANIFEST.md` (pre-refresh) | +8 since 2026-06-02 (Edwards, Butler, Bounds, Rutherford/Boston/Murray works). |
| 4 | superseded | `docs/PROJECT_CONTEXT.md` §1/§13: "HuggingFace publish is the next major milestone" / "publish has not been run yet" | Publish infra built (`df212439`, `export_hf_dataset.py`, upload script); README states dataset published to HuggingFace; counts reconciled to a June 2026 export | `docs/PROJECT_CONTEXT.md:13`, `:310` | Doc predates the publish work. |
| 5 | superseded | `docs/PROJECT_CONTEXT.md` §9: "Current state: 1,343 files, 159 errors, 187 warnings" | 1,359 files on disk; validation numbers undated and stale | `docs/PROJECT_CONTEXT.md:245` | Snapshot likely from April 2026. |
| 6 | resolved 2026-07-06 | `docs/PROJECT_CONTEXT.md` §2 + HF dataset card "What's included": "structured_text 165 works" | Batch 09 replaced the card's stale hand-written category table with counts from `build/tools/count_dataset_records.py`. | `docs/HUGGINGFACE_DATASET_CARD.md`, `docs/WORK_CATALOG.md` | The current generated count is 288 structured-text work units; the historical `PROJECT_CONTEXT` citation remains archived context only. |
| 7 | resolved 2026-07-06 | HF dataset card: "reference 30,155 entries" and "topical_reference 5,945 topics" | Batch 09 replaced the card's stale hand-written category table with counts from `build/tools/count_dataset_records.py`. | `docs/HUGGINGFACE_DATASET_CARD.md`, `docs/WORK_CATALOG.md` | Current public inventory counts reference/topical as work units first, with source records and flattened HF rows counted separately. |
| 8 | resolved 2026-07-06 | README headline: "541,000+ structured records" | Batch 09 replaced the hand-written headline with `build/tools/count_dataset_records.py`: 408 recognized work units, 543,795 top-level source records, and 803,985 flattened HuggingFace JSONL rows. | `README.md`, `docs/HUGGINGFACE_DATASET_CARD.md`, `docs/WORK_CATALOG.md` | Public inventory is now author/work-led. Export rows are documented as a subordinate technical count. |
| 9 | drift | `docs/PROJECT_CONTEXT.md` §2 schema list: `hymn.schema.json`; `docs/SCHEMA_SPEC.md` §12 titled `hymn` | Schema file is `schemas/v1/hymn_collection.schema.json`; validator + PROJECT_CONTEXT §5 use `hymn_collection` | `docs/PROJECT_CONTEXT.md:47`, `docs/SCHEMA_SPEC.md` §12 | Naming inconsistency only; the schema/validator agree on `hymn_collection`. |
| 10 | gap | `docs/SCHEMA_SPEC.md` §13: `liturgical_service` schema type (FUTURE JSON projection) | No `liturgical_service.schema.json`; no validator handler. BCP services are now represented in TEI IR, not a hand-built JSON schema. | `docs/SCHEMA_SPEC.md` §13; `ir/bcp/` | A record emitting `liturgical_service` would still fail today. Future publication should project from TEI when a consumer needs this JSON shape. |
| 11 | gap | Convention (repo `CLAUDE.md`, `AGENTS.md`): parser + test per source | 26 of 53 production parsers lack a directly named `tests/test_<parser>.py` | repo-root `CLAUDE.md`, `AGENTS.md` test gate | Recomputed 2026-07-16 from 55 `build/parsers/*.py` files minus the two documented non-producing helpers. Gaps predate the pre-commit gate, which only blocks *new* parsers; some parsers have coverage under differently named test files. |
| 12 | resolved 2026-07-06 | Single publish path implied by `docs/PROJECT_CONTEXT.md` §2/§3 (`export_huggingface.py` -> `exports/huggingface/*.jsonl`) | Batch 09 documented the authoritative whole-corpus path as `build/scripts/export_huggingface.py` -> `exports/huggingface/`; `build/tools/export_hf_dataset.py` remains the non-authoritative `original`/`modernised` NSH-style path. | `docs/huggingface-publishing.md`, `build/scripts/export_huggingface.py` | The live exporter now copies `docs/HUGGINGFACE_DATASET_CARD.md` to `exports/huggingface/README.md` and excludes NSH OCR/reconciliation artefacts from the whole-corpus export. |
| 13 | resolved 2026-07-06 | `build/scripts/export_huggingface.log` (2026-04-12): sermon 36, reference 11,145 | Batch 09 regenerated the local HuggingFace export: 803,985 JSONL rows, 1,814 processed files, 0 load/write errors. | `build/scripts/export_huggingface.py`, `exports/huggingface/` | At the 2026-07-06 snapshot, the export was ignored and push-pending; the authorized 2026-07-17 data upload later completed. |
| 14 | drift | `docs/PROJECT_CONTEXT.md` §2: "reference <- 6 reference works" | `data/reference/` holds the published dictionaries/encyclopedias **plus** ~80 NSH OCR per-volume/manifest files (0 published records) | `docs/PROJECT_CONTEXT.md:30` | The NSH OCR vol files under `data/reference/` are NSH-scope, not published reference records; they inflate the directory's file count. |
| 15 | superseded | `docs/PROJECT_CONTEXT.md` §11: "442 entries as of 2026-06-01" (author registry) | Not re-verified at this refresh | `docs/PROJECT_CONTEXT.md:284` | Date-stamped and ~2 weeks old; recorded as unverified, not contradicted. |

---

*Anchor created 2026-06-16; restructured 2026-07-04 (stateful Part 2 replaced by pointers).
Part 3 rows are dated audit history — the disk is ground truth.*
