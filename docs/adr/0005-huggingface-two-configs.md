# ADR-0005: HuggingFace publishes one dataset with two configs

**Status:** Accepted (2026-05-15)

## Context

The rearchitecture produces two final outputs per work: an original-spelling record and a modernised-spelling sibling. These need to publish to HuggingFace in a shape that lets consumers pick the view they want without bloated downloads.

Four candidate shapes:

1. Two separate HuggingFace dataset repos.
2. One repo, two configs (`original`, `modernised`).
3. One repo, single config, every record has a `variant` field; consumers filter client-side.
4. One repo, one record per work, each block carries both `original_text` and `modern_text` (collapses the two outputs).

## Decision

One HuggingFace dataset repo (`openchristiandata/open-christian-data`) with two configs: `original` and `modernised`. Consumers load with `load_dataset("openchristiandata/open-christian-data", "modernised")` (or `"original"`).

Within each config, records are filterable by columns (author, work, resource_type, edition). A work without a modernised sibling does not appear in the `modernised` config — cleanly missing rather than nulled.

## Consequences

**Positive**
- Configs are HuggingFace's idiomatic mechanism for exactly this case (same dataset, different views). Multi-language datasets, multi-cleaning-level datasets, multi-format datasets all use configs this way.
- Single discoverability surface. One dataset card, one URL, one place to land.
- Consumers download only what they want. The `modernised` config does not pull `original` records' bytes.
- Maps cleanly to the on-disk shape (`data/<type>/<author>/<work>/<edition>/original/` and `.../modernised/`). The publishing script reads each tree into its config without schema gymnastics.
- Honours the two-outputs hard requirement. Each variant is a distinct dataset view with its own records, metadata, and audit trail.

**Negative**
- The dataset card has to explain both configs. New consumers must read it before knowing which to use. Good documentation is necessary.
- Versioning across configs needs discipline — bumping the modernisation ruleset version triggers a `modernised`-config update without changing `original`. The dataset card has to surface this.

## Alternatives considered

- **Two separate dataset repos.** Rejected. Doubles discoverability surface; readers may find one without the other; cross-config use cases (paired original+modernised for training) get harder.
- **One repo, single config, `variant` field on each record.** Rejected. Forces every consumer to download both variants regardless of which they want — wasteful bandwidth.
- **One record per work with both texts per block.** Rejected. Collapses the two outputs into one record; loses the separate audit trails for `original` vs `modernised`; complicates the schema for the simple case where modernisation has not been done yet.
