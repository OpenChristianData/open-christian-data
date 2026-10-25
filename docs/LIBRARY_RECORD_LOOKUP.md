# Connected library-record lookup

This guide describes the read-only library-record lookup and its observable
interface. The lookup connects existing records; those records continue to own
their facts. To report a problem or propose a correction, follow the
[contribution guide](../CONTRIBUTING.md); the issue or pull request is the public
return point for a maintainer decision.

## Use

Run from the software checkout against a supplied record workspace. A public
checkout has no private production library: use `--root <record-workspace>` for
your task records. The example IDs below belong to the production library; use
the exact IDs supplied for your work. For source research without those records,
start with the [public acquisition view](ACQUISITIONS.md).

```powershell
py -3 -m build.tools.lookup_library_record --kind work --namespace ocd --id baxter-christian-directory --json
py -3 -m build.tools.lookup_library_record --kind research_lead --namespace research --id TFR-20261001-09
py -3 -m build.tools.lookup_library_record --kind source_catalog_entry --namespace tfr --id 1928-bcp --json
```

Omit `--json` for readable output of the same normalized facts. `--root` selects
the record authority checkout; the running checkout supplies the implementation
and schemas. Missing or stale connections remain visible.

For a bounded canonical identity/holdings lookup, use `--records-only`.
Research, metadata enrichment, intent, and task coverage are then unassessed.

| Kind | Namespace | Required parents |
|---|---|---|
| `work` | `ocd` | None |
| `textual_form` | `ocd` | `--work-id` |
| `edition` | `ocd` | `--work-id`, `--textual-form-id` |
| `acquisition` | `ocd` | `--work-id`, `--textual-form-id`, `--edition-id` |
| `research_lead` | `research` | None |
| `source_catalog_entry` | `tfr` | None |

Identifiers are exact. No title matching, fuzzy search, automatic promotion,
acquisition, task claim, or dispatch occurs. The reusable API is
`ocd_kernel.library.records.lookup_library_record(root, selector)`.

## Reading a result

The closed `ocd-library-record-v1` result separates resolution from collection
health. `found` means the selected record was found in its observable validated
population. It can coexist with `partial` when another required input is stale,
invalid, unavailable, or unsupported. Unavailable and invalid populations do not
produce a false negative result. An intentionally held claim remains valid research.

Identity, holdings, research, metadata, selection, and coordination have separate
health and inspection bases. The returned fingerprint binds consumed small
records, matching directory membership, routing, interface/adapter versions,
and presence/size observations. Execution time is outside that fingerprint.
Changed inputs receive one retry; repeated changes return `unstable`.

**Default inspection is records and presence/size.** It does not read retained
text bodies or TEI masters. Declared hashes, historical acceptance records,
current observed presence, and current byte integrity remain separate. A
same-size text change can leave the fingerprint unchanged: integrity is explicitly
`not_assessed`. Existing whole-library reports retain their deeper checks.

| Exit | Meaning |
|---|---|
| 0 | Found, complete declared scope |
| 2 | Invalid selector |
| 3 | Partial, unavailable, invalid/stale input, or unstable collection |
| 4 | Not found in the validated named population |
| 5 | Ambiguous source identifier; other diagnostics remain in the result |

## Owners and boundaries

| Fact | Update owner |
|---|---|
| Canonical identity | Work/form/edition sidecars and guarded identity workflow |
| Retained members and stage | Acquisition and state sidecars |
| Accepted wording and historical acceptance | TEI master, acceptance, guarded installation |
| Lead intent/disposition/resolution | Structured research queue and owning research workflow |
| Catalog observation | Retained TFR snapshot at its bound revision |
| Relationships and associations | `research/library-record-links.json`, evidence-bound research only |
| Metadata adoption/inspection | Existing authored metadata decisions; generated projections are labeled |
| Current collection intent | Applicable campaign worklist/current decision |
| Task owner/status/dependencies | The named owning tracker |
| Release selection | Existing work-level publication selection; readiness and authorization are unassessed |

The output includes update-route guidance, prerequisites, and explicit unsupported
routes. It offers no universal writer. The lead repair tool defaults to a dry run:

```powershell
py -3 -m build.tools.repair_manifest_leads
py -3 -m build.tools.repair_manifest_leads --apply
```

The current 357-record migration is already installed. Re-run this tool only
after an audited manifest change; otherwise it creates another migration for
the same population.

Apply only to the explicitly authorized target checkout. It installs immutable
preimages and a versioned migration map, validates the staged queue, rechecks
before hashes, and atomically swaps the queue last. It preserves editorial
decisions and IDs; changed claims are held. It is not an editorial revision tool.
Queue version 2.1 requires its complete immutable migration population. Future
editorial revisions need their owning explicit evidence/revision workflow.

The current queue has 357 leads: 348 conserved identities plus nine TFR additions.
One Meyer claim is held because the newer source row changes its extent/quality.
The unavailable old full manifest is not claimed recovered: exact prior queue
bytes and literal old claims are retained, and its old full-document hash remains
a historical declaration.

Both relationship endpoints must resolve to existing, unambiguous records. Targets
must be canonical; lead and source catalog endpoints are permitted only as sources. Canonical
endpoints must match the work/form/edition hierarchy; acquisition endpoints also load
and validate their exact sidecar identity and parent. This checks records, without
reading or rehashing retained text bodies. Partial containment also resolves its
containing work/form and rejects a missing form or a conflicting endpoint form.

All 15 legacy crosswalk comparisons are preserved. They lack a named historical
reviewer, so normalized links remain proposed/unresolved candidates. The old
`1928-bcp`/American collects comparison is superseded for current containment.
Nine discovery associations connect catalog entries to research leads without
asserting identical editions. Production observations retain source/date/wording;
silence about AI remains unknown, and OCR is a separate activity.

## Coordination coverage

Current project-state rows with explicit hierarchy paths and the explicitly associated
current worklist row are supported. Tasks match the exact selected subject; work-level
tasks and decisions are not relabeled as edition or acquisition tasks. Tickets support
bold `Work ID`, `Textual form ID`, `Edition ID`, and `Acquisition ID` fields (with the
required parent fields), `Lead ID`/`Research lead ID`, and `TFR entry ID`/`Source catalog
entry` fields. Untyped phrases such as “catalog entry” establish no task subject.
Library hierarchy paths retain their most specific declared scope.
Unpromoted leads and source catalog entries can have tasks without a canonical work. The 37c ticket population is historical.
Pipeline ticket references are inspected with unknown applicability unless an
owning current anchor establishes it. Dependencies resolve only within the
inspected ticket population; unresolved references remain unavailable.

Project-state prose, unassociated worklist rows, the pipeline ledger, and unified
completion-plan prose remain partially supported. `complete_explicit_scope`
means lookup finished inspecting its declared tracker locations, supported
tables and typed references. The individual population records still identify
partially interpreted prose. That expected limit is shown as scope information,
not a warning on every successful lookup. Missing required anchors or unreadable
ticket populations remain incomplete/errors; legacy ticket encoding still warns
and prevents an explicit-scope completion claim.
A valid coordination section or complete declared-scope result does not mean
the global tracker population is complete.
An unknown owner or no matching task is **not** global availability or permission
to start. Associations store references only; they do not duplicate mutable
owner/status/progress facts.

## Evidence

Lookup results bind the records and source hashes consumed by that lookup; a
guard blocks retained text-body reads. Historical implementation receipts are
maintainer evidence, rather than prerequisites for using or contributing to this
interface. Include the command, selector, and relevant diagnostic when reporting
a problem; do not upload private retained sources.

This increment creates no database, web UI, leases, enforced task assignments,
ranking, source downloads, corpus acceptance, rights clearance, or publication.
