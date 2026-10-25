# Proposed OCD library pipeline and file topology

**Status:** Design reference with implemented and pending portions. See the
[contribution guide](../CONTRIBUTING.md) for current public participation and
[command guide](LIBRARY_CONSUMER_CUTOVER.md) for supported interfaces. This sketch
explains the specification; it does not establish corpus readiness or override
canonical sidecars and executable command contracts.
**Companion specification:** `docs/OCD_LIBRARY_PIPELINE_SPEC.md`

This is the smallest end-to-end topology that implements the approved design. It
shows where authoritative facts live, what is generated, and what may be public.

## 1. End-to-end flow

```text
acquisition research
  |
  | enough evidence + real OCD intent
  v
library/works/<work_id>/work.json                 stable identity authority
library/works/<work_id>/state.json                current project-state authority
  |
  | acquire one source instance
  v
.../acquisitions/<acquisition_id>.json            exact acquisition evidence
raw/...                                            retained source bytes
  |
  | source-specific converter (OCD or EzraOCR route)
  v
reports/reconstruction/.../candidate.tei.xml      temporary candidate
reports/reconstruction/.../validation.json        generated evidence
  |
  | evidence-backed acceptance by an authorized agent or human
  v
.../editions/<edition_id>/master.tei.xml           accepted ordered-text authority
  |
  | category mapper + public schema
  +------------------------------+
  v                              v
private projection receipt       public category JSONL rows
  |                              |
  +---------- independent -------+
               checker
                  |
                  v
exports/releases/<release_id>/
  internal/                                        never uploaded
  public/                                          only uploadable tree
                  |
                  | separate explicit publish action
                  v
one Hugging Face dataset repository
  with form-based configurations
```

The important simplification is that there is no authored catalog between the
accepted TEI and the release. The release builder reads the stable sidecars and
accepted masters directly. Catalogs are reports over the same inputs.

## 2. Proposed authoritative library files

```text
library/
  corpus-manifest.json                    generated local whole-corpus view
  corpus-manifest.md                      generated, tracked readable view
  works/
    <work_id>/
      work.json
      state.json
      forms/
        <textual_form_id>/
          editions/
            <edition_id>/
              master.tei.xml
              acquisitions/
                <acquisition_id>.json
              assessments/
                <assessment_id>.json        optional, internal
              reviews/
                <review_id>.json            optional, internal
```

### `work.json`

One per work. It contains:

- immutable `work_id`;
- evidenced readable titles and creators;
- textual-form identities and relationships;
- known edition identities and relationships; and
- concise evidence pointers for disputed or non-obvious identity facts.

It does not contain text, workflow status, inferred tradition, audience, era,
themes, generic enrichment, or an open-ended metadata bag.

### `state.json`

One per work. It contains a small list of acquisition and edition targets:

```json
{
  "schema_version": "2.0",
  "work_id": "ocd-work-...",
  "targets": [
    {
      "target_id": "ocd-edition-...",
      "target_type": "edition",
      "stage": "accepted",
      "updated_at": "2026-08-31T00:00:00Z",
      "evidence": ["forms/.../editions/.../master.tei.xml"]
    }
  ]
}
```

The exact stage vocabulary belongs to the executable schema ticket. It should be
short and human-readable. Evidence checks may contradict a declared stage, and the
generated status report must show that contradiction.

### `master.tei.xml`

This is the complete accepted ordered text for one edition. The TEI header binds
the work, textual form, edition, acquisition provenance, language, revision, and
acceptance history. The body preserves source-attested content and structure.
Acceptance may be performed by an authorized agent when the defined evidence and
validation requirements pass. A separate human-verification record states if and
what a person later inspected.

### Acquisition sidecar

Each acquisition sidecar binds one exact source instance:

- `acquisition_id` and `edition_id`;
- provider and exact URL;
- access date;
- retained file references, media types, byte sizes, and SHA-256 hashes;
- source scope and any edition-identification evidence; and
- the acquisition route, including whether EzraOCR was required.

Retained bytes remain under the configured `raw/` storage root. The sidecar points
to them and verifies their identity; large source files are not duplicated beside
the TEI.

### Optional assessments and reviews

These directories exist only when records exist. An agent assessment holds
researched evidence, citations, uncertainty, and surfaced conflicts. A human review
holds only the scope and result actually inspected by a person. Neither is required
for every work and neither is public. Human verification is useful evidence, not a
mandatory gate on agent acceptance.

## 3. Acquisition research before stable identity

```text
library/
  acquisition-leads.jsonl
  acquisition-research/       evidence notes for new leads
```

The library tooling owns this queue for project-relevant leads that are too ambiguous to
mint a stable work identity. It is not a universal bibliography and not the library
catalog. A lead records only the observed claim, evidence link, acquisition intent,
and current research disposition. Once evidence establishes an in-scope work, the
stable facts move to `work.json` and the lead points to `work_id` or closes.

`research/MANIFEST.md` retains original observations and their historical
context. `library/acquisition-leads.jsonl` owns current lead disposition. Add or
resolve one evidenced lead through `build/tools/maintain_research_lead.py`, using
its dry run before an authorized `--write`; this upkeep operation preserves the
other queue records and does not replay the historical migration. Stable identity
facts belong in the work sidecars after review. Readable acquisition overviews
are generated.

Use the [queue cataloging template](examples/information-templates.md#acquisition-queue-cataloging)
for new proposals. The former `research/acquisition-leads.jsonl` location is
retired; readers and writers use the library path without falling back to an old
copy. Historical research documents and hash-bound lead history remain evidence.

## 4. Reconstruction workspace

```text
reports/
  reconstruction/
    <work_id>/
      <edition_id>/
        <run_id>/
          candidate.tei.xml
          validation.json
          source-accounting.json
          review-packet/                 only when needed
```

These are regenerable working and review artifacts, not accepted library masters.
The converter and validator must take explicit inputs. Acceptance promotes the
reviewed TEI bytes to the edition's `master.tei.xml` and updates `state.json` in the
same accepted change.

EzraOCR uses its own internal working topology. OCD does not import that topology;
it receives the versioned handoff contract and accepted TEI evidence.

## 5. Schema topology

```text
schemas/
  v2/
    _defs/
      identifiers.schema.json
      objective-metadata.schema.json
      public-provenance.schema.json
    work.schema.json
    state.schema.json
    acquisition.schema.json
    agent-assessment.schema.json
    human-review.schema.json
    public-row.schema.json
    categories/
      bible.schema.json
      commentary.schema.json
      quotations.schema.json
      prose.schema.json
      poetry.schema.json
      sermons.schema.json
      catechisms.schema.json
      doctrinal-documents.schema.json
      reference-entries.schema.json
      topical-indexes.schema.json
      devotionals.schema.json
      prayers.schema.json
      hymns.schema.json
      liturgies.schema.json
    projection-receipt.schema.json
    release-selection.schema.json
    release-report.schema.json
```

This is a closed, versioned package. Category schemas extend the common public row
only with required functional structure. They do not repeat full work or edition
metadata definitions.

`agent-assessment` and `human-review` are optional narrow record types, not required
sidecars and not new workflow engines. If implementation shows that one simple
common review-record schema can express both without blurring authority, these two
files may be merged during the executable-schema ticket.

Legacy public-record schemas remain available for their existing callers until
consumer cutover and retirement gates pass. The v1 directories also contain
retained source, witness and private contracts: their versioned directory name
is not permission to delete them. Retire only the explicitly inventoried legacy
public-product schemas; current public rows use the v2 category contracts.

## 6. OCD-local runtime topology

```text
ocd_kernel/
  library/
    identities.py                 load and validate work sidecars
    state.py                      load, validate, and reconcile state
    acquisitions.py               exact acquisition bindings
    views.py                       generated catalog and status views
  tei/
    profile.py                    common vocabulary and permitted patterns
    extensions.py                 declared source/category extensions
    validation.py                 generic TEI plus OCD semantic validation
    conformance.py                real-corpus pattern checks
    acceptance.py                 accepted-master binding
  projection/
    envelope.py                   common public row envelope
    receipt.py                    private row/TEI correspondence
    categories/
      bible.py
      commentary.py
      quotations.py
      prose.py
      poetry.py
      sermons.py
      catechisms.py
      doctrinal_documents.py
      reference_entries.py
      topical_indexes.py
      devotionals.py
      prayers.py
      hymns.py
      liturgies.py
  release/
    selection.py                  explicit accepted-master selection
    assemble.py                   fresh private/public build
    verify.py                     independent mechanical checker
    public_allowlist.py           public-tree boundary
```

The existing package name can remain. “Separate kernels” means EzraOCR no longer
imports this runtime package; it does not require a cosmetic package rename.

Thin command-line entry points stay outside the domain modules. This original
design sketch names intended roles, not the current executable commands; use
[the consumer guide](LIBRARY_CONSUMER_CUTOVER.md) for maintained entry points:

```text
build/tools/
  build_library_views.py
  build_hf_release.py
  check_hf_release.py
  publish_hf_release.py           separate explicit remote action
```

The first three roles are local and offline. Publication is a separate action;
this sketch does not establish an implemented or authorized upload command.

## 7. Generated internal views

```text
library/
  corpus-manifest.json              local generated inventory
  corpus-manifest.md                tracked readable inventory
reports/
  library/
    project-status.json           target stages plus contradictions
    acquisition-queue.json        actionable acquisition targets
```

`library/corpus-manifest.md` is the generated readable snapshot tracked in Git.
The full `library/corpus-manifest.json` stays local because its expanded bindings
can exceed Git file-size limits. Both report the in-scope works, textual forms,
editions, acquisitions, accepted masters, and target states at generation time.
They are not edited by hand or treated as a second authority. Freshness checks
compare them with the per-work sidecars and accepted evidence.

Regenerate the local views through the owning command:

```powershell
py -3 -m build.tools.build_library_views --root . --in-place
```

The reports are disposable. Deleting and rebuilding any generated view must not
lose an authoritative fact. The generators fail when IDs collide, required
connections break, accepted masters do not match sidecars, declared stages conflict
with evidence, or a generated corpus view is stale.

This replaces the expanded `WorkCatalog` control plane. A small read-only library
view may retain the useful catalog name, but it cannot own reconstruction routes,
candidate selection, acceptance, or publication state.

## 8. Projection and release topology

```text
exports/
  releases/
    <release_id>/
      internal/
        release-selection.json
        release-report.json
        projection-receipts/
          <edition_id>.json
        checks/
          independent-check.json
      public/
        README.md
        data/
          bible/train.jsonl
          commentary/train.jsonl
          quotations/train.jsonl
          prose/train.jsonl
          poetry/train.jsonl
          sermons/train.jsonl
          catechisms/train.jsonl
          doctrinal_documents/train.jsonl
          reference_entries/train.jsonl
          topical_indexes/train.jsonl
          devotionals/train.jsonl
          prayers/train.jsonl
          hymns/train.jsonl
          liturgies/train.jsonl
```

Empty configuration files are not published merely to complete a list. The private
release report accounts for requested configurations with zero publishable rows and
states why. The public dataset card lists only actual public files and configurations.

The upload allowlist can select only the `public/` directory. A local release is not
a live publication and does not prove remote state.

## 9. Public row shape

The executable row contracts are maintained under `schemas/v2/`, with usage
described in [the consumer guide](LIBRARY_CONSUMER_CUTOVER.md). The following
original design example illustrates the intended relationships; it is not a
schema-valid payload or a substitute for the current category schemas:

```json
{
  "record_id": "ocd-edition-...:unit-000017",
  "sequence": 17,
  "work_id": "ocd-work-...",
  "textual_form_id": "ocd-form-...",
  "edition_id": "ocd-edition-...",
  "category": "sermons",
  "language": "en",
  "text": "Readable source-faithful text",
  "locator": {
    "sermon_number": "12"
  },
  "provenance": {
    "edition_title": "Source-attested title",
    "source_url": "https://example.test/source",
    "accessed_at": "2026-08-31",
    "rights": "public-domain"
  },
  "representation_revision": "1.1"
}
```

`locator` is closed by category. It is not a generic arbitrary object. Category
fields then add only required structure—for example sermon sections and scripture
references, hymn stanzas and hymnal occurrence, or liturgy roles and alternatives.

## 10. One fixture proves the topology

```text
tests/fixtures/library-pipeline/
  library/...
  raw/...
  expected/
    reports/library/...
    exports/releases/test-release/public/...
    exports/releases/test-release/internal/...
```

One end-to-end test invokes the view generator, release assembler, and independent
checker against this fixture. It proves that the topology works as one system before
the real library is cut over.

The TEI standard itself uses a broader real-corpus suite:

```text
tests/fixtures/tei-conformance/
  <real-work-and-pattern>/
    extract.tei.xml
    origin.json                 work, edition, source, and original location
    expected-conformance.json
```

It includes every structural pattern observed in the current accepted/current TEI
corpus and multiple real examples when texts in one category genuinely differ. The
common profile standardizes equivalent concepts; declared extensions preserve real
variation. The assessment ticket decides the smallest executable combination of
ODD, Schematron, and controlled registries rather than assuming one in advance.

## 11. Cutover map

| Current surface | Target disposition |
|---|---|
| `research/MANIFEST.md` | Preserve as cutover evidence; move facts to work/state/lead authorities; replace live overview with generated reports |
| Expanded `WorkCatalog` | Replace with sidecar readers, a durable generated corpus manifest, and disposable status views |
| `sources/**/*.source-manifest.json` | Split exact acquisition evidence from executable reconstruction configuration; preserve exact hashes and route evidence where still required |
| Candidate packages | Keep as regenerable reconstruction/review evidence, not library identity or release selection authority |
| `ir/` accepted/candidate paths | Move accepted edition masters into the stable work hierarchy; keep candidates in reports |
| Legacy `data/` JSON | Stop using as public-product source; regenerate replacement rows from accepted TEI; retire only after consumer cutover and whole-corpus rehearsal |
| Current `build/tei/project_hf.py` | Reuse correspondence lessons; replace its generic clean-text row contract with the category profiles |
| Current `build/tei/build_hf_release.py` | Rework or replace selection and assembly around accepted masters and private/public roots |
| Current loss receipts | Reuse useful invariants in the versioned projection receipt and independent checker |
| Shared OCD/Ezra runtime kernel | Freeze the file contract early, then replace with separate runtimes plus duplicated boundary schemas/fixtures before adding substantial new OCD pipeline code |

No current artifact is deleted merely because this topology is approved. Removal
happens only after its replacement consumer path passes the end-to-end seam and the
cutover ticket explicitly accounts for it.
