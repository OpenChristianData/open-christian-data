# Dataset Production — Project State (Anchor Doc)

**This is the cold-session anchor for the dataset-production half of Open Christian Data**: the
pipeline that turns public-domain Christian texts into validated JSON committed to `data/` and
published to HuggingFace — sources, parsers, schemas, validation, the published dataset, and
provenance/licensing obligations. A cold session working on the dataset should read this first.

It carries the context a session cannot infer from code (Part 1) and an audit of what has drifted
between the docs and reality (Part 3), mirroring `docs/NSH_PROJECT_STATE.md`.

> **Current state lives in the tracker:** `plans/2026-07-03-next-units-execution/00-progress-tracker.md`
> (execution plan: `00-execution-plan.md` in the same dir; master plan / design of record:
> `plans/2026-07-03-next-units-of-work.md`). This anchor owns Part 1 (invariants + decisions) and
> Part 3 (append-only audit history) only. When any status prose here conflicts with the tracker,
> the tracker wins. This structure was set by the 2026-07-04 architecture review
> (`plans/2026-07-04-fable-architecture-review.md` — a dated record, not a live source of truth).

**Scope boundary.** The *other* half of the project — the New Schaff-Herzog (NSH) OCR rebuild and the
gold-free corrector stack — is owned by `docs/NSH_PROJECT_STATE.md` and is out of scope here. The
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

**The IR is TEI.** Every source normalizes raw -> TEI IR (human-verifiable; CETEIcean viewer at
`viewer/index.html`) -> projections, each with a `loss-receipt-v1` coverage ledger. City of God is
proven end-to-end for both renderings (`ir/augustine/`), census-gated at the ID-set level,
schema-valid against vendored TEI P5 4.11.0 (`build/tei/vendor/`). Toolchain: `build/tei/` (census,
converters, validate, project_hf, check_ledger). Rules a session must know:

- IRs are built from RAW sources, **never** from `data/` JSON.
- One TEI per rendering; xml:ids are source-derived (deep-link anchors — never renumber).
- Any `data/` commit needs a writer manifest (`PIPELINE_REFERENCE.md` §1).
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
   `plans/2026-07-03-next-units-execution/00-progress-tracker.md` — the ONE dataset-side tracker,
   updated every session. Execution design: `00-execution-plan.md` in the same dir.
2. **Acquisition (what's in the corpus, what's next, what's blocked):** `research/MANIFEST.md`.
3. **Record counts:** the disk is ground truth — re-derive, never quote a doc:

   ```
   py -3 -c "import json,glob,collections; from pathlib import Path; c=collections.Counter(); f=collections.Counter()
   for p in glob.glob('data/**/*.json', recursive=True):
       cat=Path(p).relative_to('data').parts[0]
       d=json.load(open(p,encoding='utf-8'))
       arr=d.get('data') if isinstance(d,dict) else d
       c[cat]+= len(arr) if isinstance(arr,list) else 0; f[cat]+=1
   for cat in sorted(c): print(f'{cat:24} files={f[cat]:5} records={c[cat]}')
   print('TOTAL files=',sum(f.values()),'records=',sum(c.values()))"
   ```

4. **Fidelity state per format family:** `docs/FORMAT_STATE_MAP.md`.
5. **Publish state (HF export paths, card counts):** owned by the campaign's batch 09
   (publish-truth); process docs `docs/huggingface-publishing.md` + `docs/HUGGINGFACE_DATASET_CARD.md`.
6. **Per-source licensing obligations:** `docs/LICENSING.md` (the one attribution-ask deliverable,
   Hymnary.org, is satisfied at `data/hymns/hymnary-pd/README.md`).

This anchor owns Part 1 (invariants + decisions) and Part 3 (append-only audit history) only.

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
| 6 | drift | `docs/PROJECT_CONTEXT.md` §2 + HF dataset card "What's included": "structured_text 165 works" | 283 works on disk | `docs/PROJECT_CONTEXT.md:26`, `docs/HUGGINGFACE_DATASET_CARD.md` | +118 works since the doc/card snapshot. |
| 7 | drift | HF dataset card: "reference 30,155 entries" and "topical_reference 5,945 topics" | reference 30,778; topical-reference 5,322 on disk | `docs/HUGGINGFACE_DATASET_CARD.md` | A ~623 offset appears in both (opposite signs) — possibly a reference/topical reclassification between card snapshot and disk; recorded, not theorized away. |
| 8 | drift | README headline: "541,000+ structured records" | 296,318 list-shaped records on disk; dataset-card per-config record numbers sum to ~261k | `README.md:5` | Not reproducible from a top-level per-record count. Appears to count `structured_text`/`doctrinal_document` at flattened leaf-block granularity (works + nested blocks ≈ 540k). Methodology undocumented. |
| 9 | drift | `docs/PROJECT_CONTEXT.md` §2 schema list: `hymn.schema.json`; `docs/SCHEMA_SPEC.md` §12 titled `hymn` | Schema file is `schemas/v1/hymn_collection.schema.json`; validator + PROJECT_CONTEXT §5 use `hymn_collection` | `docs/PROJECT_CONTEXT.md:47`, `docs/SCHEMA_SPEC.md` §12 | Naming inconsistency only; the schema/validator agree on `hymn_collection`. |
| 10 | gap | `docs/SCHEMA_SPEC.md` §13: `liturgical_service` schema type (FUTURE) | No `liturgical_service.schema.json`; no validator handler | `docs/SCHEMA_SPEC.md` §13 | Documented as deferred pending a BCP parser; a record emitting this type would fail. |
| 11 | gap | Convention (repo `CLAUDE.md`, `AGENTS.md`): parser + test per source | 28 of 49 production parsers lack `tests/test_<parser>.py` | repo-root `CLAUDE.md`, `AGENTS.md` test gate | Gaps predate the pre-commit gate, which only blocks *new* parsers. OCR `s1_*` parsers 9/9 covered. |
| 12 | drift | Single publish path implied by `docs/PROJECT_CONTEXT.md` §2/§3 (`export_huggingface.py` -> `exports/huggingface/*.jsonl`) | Two paths coexist: live flat-per-schema-type export, plus a new `original`/`modernised` layout (`export_hf_dataset.py`, B17) populated only with 13 NSH `original/*.json`, 0 modernised | `docs/PROJECT_CONTEXT.md:64`, `build/tools/export_hf_dataset.py`, `docs/HUGGINGFACE_DATASET_CARD.md` | Dataset card is internally split: YAML + R60/R64/R65 describe the new layout; "What's included" describes the live one. |
| 13 | superseded | `build/scripts/export_huggingface.log` (2026-04-12): sermon 36, reference 11,145 | disk sermon 5,299, reference 30,778; README reconciled to a later June export | `build/scripts/export_huggingface.log`, commits `fff5ae3f`/`3ce19225` | The April log predates most acquisition; it does not describe current published reality. |
| 14 | drift | `docs/PROJECT_CONTEXT.md` §2: "reference <- 6 reference works" | `data/reference/` holds the published dictionaries/encyclopedias **plus** ~80 NSH OCR per-volume/manifest files (0 published records) | `docs/PROJECT_CONTEXT.md:30` | The NSH OCR vol files under `data/reference/` are NSH-scope, not published reference records; they inflate the directory's file count. |
| 15 | superseded | `docs/PROJECT_CONTEXT.md` §11: "442 entries as of 2026-06-01" (author registry) | Not re-verified at this refresh | `docs/PROJECT_CONTEXT.md:284` | Date-stamped and ~2 weeks old; recorded as unverified, not contradicted. |

---

*Anchor created 2026-06-16; restructured 2026-07-04 (stateful Part 2 replaced by pointers).
Part 3 rows are dated audit history — the disk is ground truth.*
