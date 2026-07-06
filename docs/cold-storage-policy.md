# Cold-storage policy

This policy covers migration of release-bound large artifacts out of hot
storage after publication, while preserving replay, provenance, and audit
access. Planned tools are `build/tools/plan_cold_storage_migration.py` and
`build/tools/apply_cold_storage_migration.py`. They are not implemented in this
batch.

## Scope

Candidate artifacts include raw JP2/ZIP files, superseded snapshots, and
audit-only artifacts. Migration never means silent deletion. Every migrated
artifact remains addressable through a local pointer manifest.

## Age window

The default age window is 180 days after release publication. Maintainers may
tune the window. The trigger point is the S6 maintainer decision, not an
automatic background process.

## Pinned-not-migrated gate

Never migrate anything in:

- the currently pinned release-verification set
- current active build artifacts
- the current gold sample
- the current decisions store
- the current promoted matrix snapshot
- any unresolved reviewer queue

## Provenance checks

Migration requires two provenance checks:

- before migration, verify the artifact path and content hash against the
  manifest
- after restore simulation, verify restored bytes against the same content hash

Hash mismatch after restore simulation fails the migration.

## Addressability

Migrated artifacts must stay addressable by:

- manifest path
- content hash
- storage URI
- restore instructions

The hot-storage replacement is a local stub or pointer manifest. It must never
be a silent missing file.

## Cold-storage destination

The cold-storage destination must be outside the sync folder and outside every
cloud-sync scope. This is a hard rule. A destination inside a synced workspace
fails validation.

## Planned outputs

The deferred tools will write:

- `reports/storage/cold_storage_plan.json`
- `reports/storage/cold_storage_plan.md`
- `reports/storage/cold_storage_migration_<run_id>.json`
