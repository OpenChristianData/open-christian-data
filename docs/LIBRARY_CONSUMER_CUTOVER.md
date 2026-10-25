# Library consumer cutover

This guide describes supported library and release commands. The
[contribution guide](../CONTRIBUTING.md) explains how to propose a change or ask
a maintainer about current work. Commands require their declared inputs;
missing inputs and unsupported source shapes remain explicit gaps.

## Public software and dataset files

The GitHub checkout contains software, schemas, documentation and legacy/example
data.
Production library records, retained sources, private review receipts and full
release packages are separate inputs; installing the software does not acquire
them. The small public-only check is in the contribution guide.

A generated dataset has its own README, data guide, item-level terms, source
notices and downloads, with links relative to that dataset's root. Its private
preparation templates are not GitHub consumer documents. Read those delivered
files for the exact selected release; software checks do not approve its text,
rights or publication.

## Browse declared works

Inspect one exact work through current records without research/tracker enrichment:

```powershell
py -3 -m build.tools.lookup_library_record --kind work --namespace ocd --id asv --records-only
```

Readable lookup summarizes identity, recorded stage, acceptance scope, limitations
and authority paths. Add `--json` for all bound records/evidence and update routes;
omit `--records-only` for explicit research, metadata, selection and task enrichment.
Presence and recorded acceptance do not verify current text bytes.

Current assignments stay in their owning campaign tickets. Supported explicit
fields are `Work ID` (or typed form/edition/acquisition/lead IDs with parents),
`Task applicability`, `Owner`, `Status`, `Next action`, `Blocked by`, and
`Successor`. Lookup reads them from the tracker and exposes resolvable blocker/
successor paths; superseded/completed assignments are historical. Unsupported
prose remains partial coverage. A missing match does not establish availability.

```powershell
py -3 build/tools/report_library.py --json
py -3 build/tools/report_library.py
py -3 build/tools/report_library.py --search "Augustine" --category prose --stage accepted --limit 20
py -3 build/tools/report_library.py --creator "John Owen" --json
py -3 build/tools/build_book_index.py --output <explicit-index.md>
```

Browse v1 reads current validated work/acquisition records and recorded state,
observing master/acceptance file presence without reading source or TEI bodies.
Counts distinguish recorded accepted editions from observed master files; neither
proves current text integrity or release eligibility. CLI results default to 50
matching works; `--offset` and `--limit` page deterministic work-ID order. The
shared callable retains an unbounded default for existing index consumers.
Search matches tokens across ID/title/declared creators; creator-only queries
leave unknown creators unmatched. Category/stage filters apply to the same edition.
CVW reuses the token matcher while keeping its own candidate-availability filter.
Deep generated views and their freshness checks still perform their explicit audit.
Saved
catalogs are reports, not admission authority. Declared-library counts, historical
holdings and selected-release row counts describe different populations.
Error-level authority issues return nonzero; a diagnostic count is not acceptance.
Metadata assessment uses declared sidecars by default; historical comparison is
explicit. Source-review tools retain historical evidence where their contracts
require it, without making that evidence replacement authority.

CVW launch and runtime materialization default to the declared-library route.
An explicit `--catalog` selects historical review. Missing declarations are
handoff gaps; do not infer acceptance from the existence of a candidate or master.
Selected source and candidate artifacts remain read-only review inputs.

Install an already promoted work with the shared guarded route:

```powershell
py -3 build/tools/install_accepted_work.py --root <repository-root> --promoted <promoted-root> --work <work-id>
```

The command validates and installs the named work through the shared kernel installer, retaining the existing rollback and evidence checks. It does not create or promote a master.

For an accepted representation update, supply `--expected-old <snapshot.json>`.
When the independently reviewed generation also updates declarations or
publication metadata, supply `--reviewed-new <snapshot.json>` containing its
complete incoming file hashes. Both snapshots are checked under the work locks.
Existing declarations, accepted identities, acquisition bytes and unrelated
state targets are preserved. Superseded edition rights assessments may move
only into a new `publication/history/<packet>/` file with the same name and
bytes. The transaction retains the complete previous generation for recovery.
The snapshot is the complete work-relative file-to-SHA-256 map reviewed before
installation. A stale snapshot or an unrelated authority change is rejected;
the operation preserves the prior work generation for rollback. To add one
edition while preserving all existing editions, also supply
`--add-edition <textual-form-id> <edition-id>`. Source and notice files outside
the work tree must already be retained at their declared locations. These
operations do not clear rights or select text for publication.

Original-composition language and work classification use typed, work-scoped
source-metadata claims. The work record explicitly names the metadata subject
and adopted value. Only supported claims adopted into the exact work target
can supply public `provenance.original_language` or `provenance.work_kind`.
Evidence-only claims stay unpublished; missing claims stay absent. Row `language`
still describes the edition/textual form. Classification uses the maintained
work-kind vocabulary, not TEI division types.

New release work-metadata receipts use v3, an outer layer applied after the
publication transform and selected license. Existing v2 receipts remain readable.
Both bind the work, selected claims and composed rows. Verification checks
current evidence and then independently checks the
underlying category projection. Canonical installation requires shared metadata
and bound evidence in the destination repository; it rolls back if a declared
claim cannot be verified. Installing one work does not replace the shared index.

## Assemble, read and count an offline release

For the current library cohort, use the private editorial publication profile:

```powershell
py -3 build/scripts/export_huggingface.py --root <authority-root> --profile <library-publication-profile.json> --release-id <release-id> --output <fresh-release-directory> --evidence-dir <private-evidence-directory>
```

This route derives the selection and rights/notices from current library
authority, streams JSONL and Arrow, independently verifies every selected item,
and checks both reader modes before promotion. Its pinned build manifest,
reader proof, and `internal/checks/build-ready.json` bind the same checked
files. A failed run leaves private diagnostics without creating the requested
candidate destination. The build workspace and category-scoped reader caches
use the output volume; choose the durable D: export route when C: is constrained.
Preflight space estimates include headroom but are not a guarantee for arbitrary
source adapters. No upload is performed.

An optional `--previous-release <ready-candidate-directory>` reuses projections
only with matching input/range bindings and fresh independent authority checks.
It creates ordinary new output files and no duplicate payload cache. Historical
packages without the new manifest/readiness bindings use the independently
checked stage-recovery route below.

### Resume an interrupted private build

Use the configured project Python runtime. Resume reads the retained stage and
writes a fresh destination; it never truncates or repairs the original stage.

```powershell
& <configured-python> build/scripts/export_huggingface.py --root <authority-root> --profile <publication-profile.json> --resume-stage <retained-stage> --release-id <release-id> --output <fresh-release-directory> --evidence-dir <new-evidence-directory>
```

New builds save `internal/build-inputs.json` before projection and atomically
commit `internal/checkpoints/<item-id>.json` after flushing each edition's rows,
receipt and inverse. Uncommitted tails are ignored. Each recovered edition must
pass current independent source/rights checks; metadata is refreshed from current
authority, and corrupt or incompatible editions are reprojected. Checkpoints
grant no publication or final readiness. Full verification, both readers and
input-drift checks still run before promotion. Cooperative OS locks release on
process termination and prevent reading a stage owned by a running new builder.

If encoding already finished, the command reuses that assembled stage directly:
it checks and copies only accounted files, then runs terminal verification and
both readers. It does not repeat per-edition recovery or Arrow encoding. Library,
profile and Python/package inputs must match. Runtime-only changes are checked
by the fresh verifier; the new release label and input snapshot are rebound in
the destination. Changed library authority falls back to ordinary edition
recovery. The original stage stays untouched. Progress identifies the current
configuration and edition during terminal verification.

For the October 21 stage created before checkpoints existed, additionally pass
`--resume-progress <original-progress.jsonl>`. Its completion events locate
candidate ranges; current independent checking establishes their correctness.
Recovery records observed source ranges/digests and reports `legacy-verified`
separately from fingerprint-matched reuse. Use this only after stopping any old
noncooperating writer. `--resume-stage` and `--previous-release` are exclusive.

For historical or separately supplied explicit selections, retain the original
selection and use the following standalone checking sequence.

Replace placeholders with the actual authority root, original selection and a
fresh output directory. These commands do not authorize publication.

```powershell
py -3 build/scripts/export_huggingface.py --root <authority-root> --selection <original-selection.json> --output <fresh-release-directory>
py -3 build/tools/check_release_reader.py --root <authority-root> --release <release-directory> --selection <original-selection.json> --output <reader-proof.json>
```

Assembly derives rows from accepted TEI and sidecars and independently verifies
them before promotion. The exporter reports that proof. The default reader then
provides terminal full independent/privacy verification plus normal/streaming
reader evidence in its returned `verification` field. This sequence performs two
full verifications; an extra direct verifier call is redundant. Preparation
and publication remain separate maintainer decisions; this command sequence
does not authorize a remote upload.

When a task needs character/token statistics, additionally run:

```powershell
py -3 build/tools/report_release_stats.py --root <authority-root> --release <release-directory> --selection <original-selection.json>
```

Standalone statistics and reader checks reverify the original selection and release;
changed rows or mismatched selections fail. `count_dataset_records.py` and
`export_stats.py` use the same required root/release/selection inputs for current
statistics. Optional `--encoding` counts tokens from public `text` only.
Historical counter behavior requires `--legacy-catalog`.

Fresh releases contain JSONL and typed Arrow companions. Use their generated
card to load `datasets.load_dataset(public_directory, name=category, split="train")`.
The reader check verifies normal and streaming values and order. Typed Arrow
avoids date-like string inference; absent optional fields may become null.
Direct JSONL readers retain the original JSON values and field absence.

Rows with `content_format: ocd-native-content-v1` preserve ordered nested content
in `structure`. Prose units can retain parent text and child sections together.
Whole-sermon output can carry separate `front_matter`. Consumers using only
`text` do not thereby consume separate front matter or notes. Do not flatten
native structure when the consuming task needs its ordering or distinctions.

Explicit source references remain attached to their source units. Devotional
`readings[].source_reference` preserves `cRef` and `target` separately when
present. Prayer `divisions[].references` preserves ordered printed `raw` labels
and any explicit `cRef` or `target`. Topical `items[].label` preserves an explicit
subheading; its wording also remains in item text. Absent values are not inferred.
Devotional body references stay on each paragraph or verse line in optional
`references` arrays, with printed `raw` labels and separate `cRef`/`target`.
Topical `alternative_topics` retains ordered TEI headings explicitly marked
`type="alternate"`, after the main topic heading. Related-topic references
remain separate; neither links nor punctuation are treated as synonyms.
Recognized explicit targets now carry a `scripture` object with `raw`,
`normalized`, `kind`, and complete `start`/`end` endpoints. Unsupported targets
retain their wording and a visible normalization status. This is syntax and
book-code normalization, not versification validation or parsing arbitrary prose.
Where both are supported, `cRef` supplies normalization before `target`; both
source attributes remain available. Devotional readings gain `role: primary`
only from an explicit `cit type="primary-reading"`, never their list position.

Sermon `primary_reference` preserves the bounded opener reference or the native
bibliographic label and its ordered `references`. Common prose references expose
external `source_target` while retaining row/note attachment. Native prose
`source_references[].source_child_path` gives zero-based TEI child indexes from
the row's source unit; retain this location when consuming nested references.
Bible `locator.reference` derives from explicit book/chapter/verse components.
Commentary scope references, printed labels, English book names and introduction
roles remain distinct; supporting cross-references do not become primary scope.

Doctrinal `revision_history` reads explicit source revision statements, including
year, revising body and description. TEI processing `revisionDesc` is not source
history. Mixed doctrinal hierarchy retains native structure and requires explicit
source-to-TEI leaf bindings for source accounting. Entry attribution in native
sermons, prayers and commentary is separate from collection attribution.

Native prose headings with `attributes.type` of `label` or `title` retain those
roles separately in ordered content. Use the structure when that distinction
matters. Regenerate releases with the current mappings; old receipts do not
establish correspondence under a changed mapping version.

## Diagnose a selected release

```powershell
py -3 build/scripts/add_token_counts.py --root <authority-root> --release <release-directory> --selection <original-selection.json>
py -3 build/scripts/short_entries_report.py --root <authority-root> --release <release-directory> --selection <original-selection.json> --threshold 20
py -3 build/tools/audit_ref_coverage.py --root <authority-root> --release <release-directory> --selection <original-selection.json>
py -3 build/tools/audit_data_accuracy.py --root <authority-root> --release <release-directory> --selection <original-selection.json>
```

Token reporting defaults to `cl100k_base` and does not alter release rows.
Short-entry reporting requires commentary rows. Reference auditing supports
explicit catechism and doctrinal OSIS arrays and normalized scripture targets
in Bible, commentary, devotional, prayer, sermon and prose rows. References
without a supported explicit target remain visible; unsupported row/reference shapes
remain visible. Literal source references, dictionary term links and inferred
Bible identifiers are distinct contracts.

Accuracy reporting separates release integrity, public-text observations and
word distributions from unsupported outlier thresholds. An incomplete current
audit returns nonzero; it is not by itself a source-error verdict. None of these
tools fills missing fields from historical JSON.

The four diagnostic utilities retain historical behavior only when
`--legacy-data` is the first argument. Historical accuracy reporting returns 0
when its report is produced, even if it contains findings. Historical witness
check/scaffold tools additionally require explicit `--repo-root` and `--schema`;
they do not substitute acquisition schemas for the removed witness schema.

The scan-data probe belongs to EzraOCR: run
`py -3 ezra/tools/probe_nsh_scandata.py [volumes]` from that repository.
The old OCD entry reports its relocation and exits 2. The separate
`build/tools/export_hf_dataset.py` original/modernised experiment is not the
current multi-category release assembler.

## Evidence and retirement

Maintainers retain dated consumer/producer inventories and bounded release
receipts. Historical retention does not establish current public support, and a
small proof release does not establish whole-corpus review. Preserve explicit
holds; earlier installation evidence does not override later adverse findings.

`build/tools/report_corpus_cutover.py` checks every frozen target, the selected
release and the complete fixed prerequisite set. Prerequisite receipts bind the
exact scope, current inputs and successful verification result; their evidence
must cover the named gate. Missing, failed, ambiguous or stale evidence leaves
retirement not-ready. A successful reporting exit code means the report was
produced, not that retirement is authorized.

A readiness report is a dated checkpoint, not automatic current-tree
acceptance. Refresh it after required final verification. Per-work preparation
gaps can remain in a complete truthful report. Affirmative readiness is required
before retiring an old route; a not-ready result does not authorize deletion.
This guide does not claim final broad verification, whole-corpus readiness or
publication. For a public question, include the command and diagnostic in an
issue using the contribution guide.
