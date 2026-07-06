# Data structure redesign — dataset side of OCD

**Status:** Design — adversarially reviewed 2026-06-18 (DO-NOT-SHIP until the §9 findings are resolved in the implementation plan)
**Date:** 2026-06-17
**Scope:** The corpus-to-JSON layout under `data/` and the source-of-truth model behind it — the dataset-production half, not the NSH OCR pipeline.

## Decision brief

- **One canonical source of truth per drift-prone field.** Any fact repeated across files (author name, work title, publication year, tradition) lives in exactly one authoritative place; the build copies it into the output. Duplication exists only in generated files, never in hand-maintained source — so it cannot drift.
- **Canonical author records and canonical work records.** Two registries own the canonical name, slug, and metadata for every author and work; configs reference them by id rather than restating their fields. The **maintained** registries live outside `data/` (e.g. `sources/registries/`), and their `data/authors/registry.json` / `data/works/registry.json` copies are **generated** — so the source of truth is not hand-edited inside the parser-produced `data/` tree (see §9-B).
- **Keep work-kind as the physical top level** (`commentaries/`, `sermons/`, `structured-text/`, …). Finite, mandatory, schema-aligned — the right partition axis.
- **Level 2 = author, level 3 = work.** Uniform `data/<work-kind>/<author>/<work>` keying replaces today's flat-vs-nested drift. A work is a single `.json` file when it is one chunk, or a folder of unit files when it splits.
- **Files stay self-contained** (`{meta, data}` in every file — Option A). The repeated `meta` envelope is build-generated from the registries, so self-containment and the no-drift rule coexist.
- **This is a config + parser change, then regenerate** — not a hand file-move. `data/` is parser-produced.
- **Excluded:** `church-fathers/` (separate redo), the HuggingFace Parquet partitioning, and any schema-shape change.

## 1. Goals

In priority order:

1. **Internal consistency** — kill the flat-vs-nested split and the book-vs-author keying drift; one predictable rule per category. Kill silent data drift by giving every shared fact a single owner.
2. **Consumer ergonomics** — navigate by author and work; any single file is complete on its own.
3. **Scale** — the layout and the source-of-truth model stay sane at 10× the current source count.

Explicitly *not* a goal: mirroring the published Parquet layout. The repo tree serves git browsing and parser output; the published dataset is flattened Parquet where the directory tree is irrelevant.

## 2. Current state (verified 2026-06-17)

- 1,458 data files across 14 top-level categories under `data/`.
- Level 2 is inconsistent: some categories nest by source (`bible-text/bsb/…`, `commentaries/calvin/…`), others are flat files (`catechisms/heidelberg-catechism.json`, `structured-text/augustine-on-the-trinity.json`).
- Keying drifts: `church-fathers/` mixes Bible-book keys (`1-corinthians.json`) with author keys; `structured-text/` squashes `author-work` into one slug.
- 454 distinct authors; ~140 files have no single personal author.
- Every file is `{meta, data}`: `meta` describes the source and is identical across a source's unit files; `data` holds the records.
- **Drift surface today:** a `sources/**/config.json` (298 of them) restates author facts (`author`, `author_birth_year`, `author_death_year`), work facts (`title`, `original_publication_year`, `language`, `original_language`, `tradition`, `era`, `audience`, `work_kind`), and source facts (`source_url`, `source_hash`, …) all in one record. The author and work facts are then copied again into every output file's `meta`. The same author's birth year or a work's title can therefore be stated differently in different configs with nothing to catch it.
- `data/` is parser-produced. Output paths come from parser constants (e.g. `sword_commentary.py` → `data/commentaries/{id}/`) and `output_file` in configs.
- `data/authors/registry.json` already exists: 446 entries (`author_id`, `display_name`, `aliases`, `birth_year`, `death_year`, `tradition`, `works`). No works registry exists yet.

## 3. Principle: one canonical source of truth per drift-prone field

A field is **drift-prone** when the same logical value appears in more than one file and could be edited in one without the others. The rule: each such field has exactly one authoritative owner, and every other appearance is generated from it.

| Field group | Examples | Canonical owner | Configs/files hold |
|---|---|---|---|
| Author facts | name, slug, birth/death year, aliases | authors registry (maintained in `sources/registries/`, generated into `data/authors/registry.json`) | `author_id` only |
| Work facts | title, slug, publication year, original language, tradition, era, audience, work_kind | works registry (new; same maintained-in-`sources/`, generated-into-`data/` split) | `work_id` only |
| Source/acquisition facts | source URL, hash, format, edition, download date | the source's own `config.json` | the facts themselves (this *is* the SSOT) |
| Controlled vocabularies | tradition, era, audience, work_kind, license enum values | `schemas/v1/` | reference the enum |
| Book ↔ OSIS mapping | book names, OSIS codes, ordering | the shared normalizer in `build/lib/` | call it |

The build **denormalizes**: it joins `author_id` + `work_id` + source config, resolving each field from its owner, and writes the self-contained `{meta, data}` file. The duplication a reader sees in the output is a projection of single sources — regeneration rewrites it, so it cannot silently diverge **for fields the build owns**. Caveat (see §9-C): some parsers preserve hand-applied corrections across regeneration (`build/lib/parser_regen_safety.py`), so regeneration is not a blanket overwrite — the SSOT metadata pass must respect those correction ledgers, not clobber them.

This is the rule that lets Option A (self-contained, duplicated `meta`) and "no drift" hold at once: **DRY at the source layer, denormalized at the output layer.**

### 3.1 Canonical author records

- Each author has one **canonical full name** (`display_name`) and one **slug** (kebab-case of the name: `Augustine of Hippo` → `augustine-of-hippo`).
- `meta.author` carries the canonical full name verbatim, identical across every work by that author; the author folder is the canonical slug.
- The registry owns name, slug, aliases, dates, and tradition. Configs carry `author_id` only — the duplicated `author`, `author_birth_year`, `author_death_year` fields come out of configs.
- Consequence: short folder slugs become full-name slugs — `commentaries/calvin/` → `commentaries/john-calvin/`, `commentaries/barnes/` → `commentaries/albert-barnes/`.

### 3.2 Canonical work records (new)

- A new `data/works/registry.json` parallels the authors registry. Each entry: `work_id`, canonical `title`, `slug`, `author_id` (or `contributor_ids` for multi-author works), `original_publication_year`, `original_language`, `tradition`, `era`, `audience`, `work_kind`, `aliases`.
- `meta.title` and the work-level metadata in every output file resolve from this record — today they are restated in every config and copied into every unit file (e.g. `"Calvin's Collected Commentaries"` repeated across all 49 Calvin files).
- The work folder/file slug is the work's canonical `slug`.
- `work_id` **equals the existing `resource_id` / `meta.id`** wherever possible — it is not a new parallel namespace. The canonical-name slug used for the *folder path* is a separate, display-facing field; `work_id` (= `resource_id`) stays the stable record key. Any case where they must differ goes in an explicit mapping table (see §9-E). This keeps record-internal ids (`entry_id` and the per-schema id fields) unaffected by the path move — they are content/parser-derived, never path-derived (see §9-D).

### 3.3 Naming convention

- **Short form** for canonical names, for now: `A. A. Hodge`, `C. H. Spurgeon`, `Augustine of Hippo` — not the fully expanded `Archibald Alexander Hodge`. The registry's `aliases` field holds the long form and other variants so search still resolves them. This can be revisited later without breaking ids (the slug is the key, not the display string).
- **The slug is the kebab-case of the canonical short-form name** (`A. A. Hodge` → `a-a-hodge`, `Augustine of Hippo` → `augustine-of-hippo`), used for both the folder name and the `author_id` / `work_id`.
- **One pass, both layers.** Filename/slug consistency is a lower priority than metadata + SSOT consistency, but the same registry resolution produces both — so they are normalized together rather than as separate efforts.

## 4. Target structure

### 4.1 The three rules

1. **Top level = work-kind.** Unchanged. One folder per schema type.
2. **Level 2 = author** (always a folder), named by the canonical author slug.
3. **Level 3 = work.** A `.json` file if the work is a single unit; a folder of unit files if it splits into many.

```
data/
  structured-text/
    augustine-of-hippo/
      on-the-trinity.json          # single-unit work = file
      confessions.json
      city-of-god/                 # multi-unit work = folder
        book-01.json
        book-02.json
    john-calvin/
      institutes-of-the-christian-religion.json
  commentaries/
    john-calvin/                   # one commentary work, split by book
      genesis.json
      romans.json
    albert-barnes/
      matthew.json
  authors/
    registry.json                  # who — canonical author records
  works/
    registry.json                  # what — canonical work records
```

The only branch is **file-vs-folder per work**, which is inherent: some works are one chunk, some are many. Everything above the work is uniformly a folder.

**Work-level elision.** When an author has a *single* work in a kind that is split into parts — a commentary split by book, a sermon collection split into chunk files — the unit files sit directly under the author folder and the redundant work folder is dropped (`commentaries/john-calvin/genesis.json`, not `commentaries/john-calvin/collected-commentaries/genesis.json`). When an author has *multiple* distinct works in a kind — the norm in `structured-text` — each work is a file or a folder of units under the author. The elision is safe because the single-work property is stable per kind: a commentary or sermon corpus is one work per author by construction.

### 4.2 Self-contained files (Option A)

Every file keeps `{meta, data}`. Opening one file gives the records *and* the author, license, and provenance, with nothing else to read. The `meta` envelope is generated from the registries and source config (per §3), so the duplication across unit files carries no drift risk. No `_meta.json` manifest.

### 4.3 Edge cases — author slug for non-single-author works

| Case | Examples | Level-2 slug rule |
|---|---|---|
| Single personal author | Calvin, Augustine, Barnes | Canonical author slug |
| Multi-author work | Jamieson-Fausset-Brown, Keil-Delitzsch | Source/work slug; individuals in `meta.contributors`, linked via `contributor_ids` on the work record |
| Bible translation (no author) | BSB, KJV | Edition slug (`bsb`, `kjv`) — already the convention |
| Institutional / compiled | Catholic Encyclopedia, Schaff-Herzog, Apostolic Constitutions | Work or institution slug |
| Anonymous short texts | Creeds, Didache | Work slug under the relevant kind |

The canonical-author rule governs single-author works. Other cases use a stable source/work slug and record people via `meta.contributors`.

### 4.4 Unit-file naming inside a work folder

- Bible-keyed works (commentaries): the book slug, lowercased (`genesis.json`, `1-corinthians.json`).
- Volume/part-keyed works: zero-padded sequence (`book-01.json`) so lexical sort matches reading order.
- Single-unit works: the work slug as the filename.

## 5. What changes, what stays

| Item | Change? | Notes |
|---|---|---|
| Top-level category folders | No | 14 work-kind folders unchanged |
| Level-2 slugs | Yes | Source/short slugs → canonical author (or source) slugs |
| File self-containment | No | Stays `{meta, data}` |
| `meta.author` values | Yes | Resolved from authors registry; normalized to canonical full name |
| `meta.title` / work metadata | Yes (source) | Resolved from works registry; output shape unchanged |
| `data/works/registry.json` | New | Canonical work records |
| `sources/**/config.json` | Yes | Slimmed: reference `author_id` + `work_id`; drop duplicated author/work facts |
| `meta.id` / `resource_id` | No | Stays stable; maps to `work_id` |
| Record-internal ids (`entry_id`, `document_id`, verse refs) | No | Content/parser-derived, never path-derived — unchanged by the move. NB: not universal (`entry_id` prefixes can differ from `meta.id`; ~193 record files have no `entry_id`), so verification is per-schema, not one global "entry_id set unchanged" check (see §9-D) |
| Schemas (`schemas/v1/`) | No | No shape change; no enum rename |
| `structured-text` name | No | Kept (alternatives all worse — see §8) |
| `church-fathers/` | No | Excluded; separate redo |

Keeping `meta.id`/`entry_id` stable is deliberate: the restructure breaks no downstream reference to a record id, and the published dataset's record ids are unchanged.

## 6. Migration approach (design level)

Detailed sequencing belongs in the implementation plan; the constraints it must honor:

0. **Classify every `data/` file first** (per §9-A). Partition into record files (`{meta, data}`), auxiliary files (88 of them: manifests, catalogs, lexicon/hymns special shapes), and registries. Path rules apply only to record files; auxiliary files and parser regeneration contracts (§9-C) are handled separately. No move happens before this manifest exists.
1. **Build the registries first.** Establish canonical author records, then canonical work records, maintained under `sources/registries/` and generated into `data/` (§9-B), before touching configs — so configs reference settled ids. Reconcile every existing config's author/work facts against the registries and resolve conflicts (this is where drift already in the data surfaces).
2. **Slim the configs.** Replace duplicated author/work facts with `author_id` + `work_id`. Source/acquisition facts stay.
3. **Drive output through configs and parsers, then regenerate.** Update output paths and re-run the build; do not hand-edit `data/`. The layout and `meta` content must be reproducible from the registries + configs.
4. **Preserve git history** where files move 1:1 (`git mv` or index-staged renames per GIT-04); regenerate only where `meta` content actually changes.
5. **Couplings to resolve:**
   - `review/state/` sidecars mirror `data/` record paths (`build/lib/review_state.py`) — remap or they orphan.
   - Writer allowlist and writer manifest (`build/lib/writer_identities.py`) gate `data/` mutations.
   - Whole-tree enum-freshness gate runs on `data/` changes (see `PIPELINE_REFERENCE.md`).
   - README "Repository structure" section and in-repo path examples.
6. **Verification:** record count per category before == after; every file validates against its schema; for every output file, `meta.author` and `meta.title` equal the registry-resolved value (the no-drift invariant, mechanically checkable); `entry_id` set unchanged; no orphaned `review/state/` sidecars.

## 7. Out of scope

- `church-fathers/` restructure (separate effort).
- HuggingFace Parquet partitioning.
- Any schema shape or enum change.
- The `_meta.json` manifest split (Option C — rejected; breaks self-containment for a parser-internal win).

## 8. Rejected alternatives

- **Author-first top level.** 454 author folders (vs 14), unbounded growth, schema-mixing within an author (Wesley = commentary + sermons; Spurgeon = sermons + commentary + devotional), and ~140 author-less files needing a `various/` bucket. Author browsing is served by the registry index instead.
- **Folder-only-if-multi-unit (Option B).** Reintroduces a depth branch and forces a file move the moment a single-unit source gains a second unit.
- **Manifest split (Option C).** Splits each file across `_meta.json` + records; needs a schema change; helps parser tooling, not consumers. The SSOT principle (§3) already removes the duplication concern that motivates C, without splitting the output files.
- **Renaming `structured-text`.** ~15 alternatives tested (`books`, `works`, `treatises`, `theological-works`, `volumes`, `divinity`, …); each was too plain, too narrow, or too obscure for a genuinely heterogeneous catch-all (treatises + history + biography + letters). `structured-text` is the honest label; renaming carries `schema_type`/schema-file/enum/parser blast radius for no net gain.

## 9. Adversarial review findings incorporated (Codex, 2026-06-18)

An adversarial review (gpt-5.5, high effort) returned **DO-NOT-SHIP** with findings verified against the live repo. Each is now a constraint the implementation plan must satisfy before any file moves. The MINOR confirmations: the 1,458 / 298-config / 446-author counts are correct, and no author with two distinct works in one kind was found — the work-level elision rule (§4.1) survived the check.

**§9-A — Migration boundary: not every `data/` file is a record (BLOCKER).** A live scan confirms **88** files under `data/` are not `{meta, data}` records — `_manifest.json` per commentary source, `data/reference/schaff/.../catalog.json`, `data/lexicon/archaic_forms_en.json`, etc. The top-level tree also includes `hymns` and `lexicon`, which the §4 rules did not name. **Constraint:** the plan must first build an explicit **file-classification manifest** — record files vs. auxiliary (manifests, catalogs, lexicon/hymns special shapes) vs. registries — and apply the path rules **only** to record files. The "move 1,458 files" framing is wrong; auxiliary files are handled by their own rules.

**§9-B — Registry governance (BLOCKER).** Making `data/authors/registry.json` + `data/works/registry.json` the hand-maintained source of truth contradicts the standing rule "do not edit `data/` JSON directly — data is produced by parsers" (`AGENTS.md`). **Resolution (adopted):** the maintained registries live under `sources/registries/`; the `data/` copies are generated like any other output. *(Open choice for the maintainer: this, vs. keeping them in `data/` and carving an explicit rule exception + edit gate. Recommendation: `sources/registries/`.)* Also: the existing author registry holds non-author junk (`"1 Corinthians"` as an author) inherited from church-fathers — clean during the registry pass, but church-fathers entries stay out of scope.

**§9-C — Parser regeneration contracts (BLOCKER).** "Regeneration rewrites the duplicated meta so it can't drift" is **not** universally true: `build/lib/parser_regen_safety.py` (`merge_single_field_regen`) preserves hand-corrected display text across regen, `ccel_expositors_bible.py` preserves prior `entry_id`s and documents direct-JSON patching, and `westminster_standard_parser.py` preserves hand-added manifest fields. A blind global metadata overwrite would destroy post-generation fixes or silently keep stale data. **Constraint:** classify every parser as **pure-regenerable / merge-regenerable / correction-ledger-dependent**, and the SSOT metadata pass must respect correction preservation per parser before any global regen.

**§9-D — Record-id reality (MAJOR).** `entry_id` does **not** universally derive from `meta.id`: `data/reference/catholic-encyclopedia-vol01.json` has `meta.id = catholic-encyclopedia-vol01` but `entry_id = catholic-encyclopedia.aachen`; ~193 record files carry no `entry_id` (bible-text keys on verse refs, catechisms on `document_id`/`item_id`). The safe invariant is narrower: **the directory move changes file paths only; record-internal ids are content/parser-derived and never path-derived.** **Constraint:** verification is **per-schema** (assert each schema's own id field is unchanged), not one global "entry_id set unchanged" check.

**§9-E — Three competing keys (MAJOR).** Keeping `resource_id` stable (`calvin-commentaries`) while renaming the folder to an author slug (`john-calvin`) and minting a new `work_id` creates up to four keys for one work. **Resolution (adopted):** `work_id == resource_id` wherever possible (no parallel namespace); the canonical-name **slug** is a separate display-facing field for the path; any divergence goes in a checked mapping table.

**§9-F — Sidecar migration is a first-class prerequisite (MAJOR).** `build/lib/review_state.py` derives `review/state/...` paths from `data/...` paths **and** stores the old `record_path` (plus checksums) inside each sidecar. Moving records without migrating sidecars orphans them or leaves embedded paths/checksums pointing at the old location. **Constraint:** sidecar migration is a named step — old→new path map, embedded `record_path` rewrite, checksum refresh, orphan check — not a "coupling to resolve later."
