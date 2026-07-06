# OCD Build Design Decisions

This file records significant design decisions made during development of the
Open Christian Data build pipeline. Entries are append-only.

---

## 2026-04-23 — `contributors` field promoted from `string[]` to `object[]`

**Decision:** The `contributors` field in all v1 schemas was changed from a flat
`string[]` to a `Contributor object[]`:

```json
{
  "contributors": [
    {
      "name": "Kirsopp Lake",
      "role": "translator",
      "affiliation": "Harvard University",
      "url": null
    }
  ]
}
```

The shared definition lives at `schemas/v1/_defs/contributor.schema.json`. All
eight v1 schemas reference it via `$ref`.

**Controlled vocabulary for `role`:**
`author | translator | editor | transcriber | compiler | contributor | narrator | annotator | digitizer`

`name` is required. `role`, `affiliation`, and `url` are optional. The schema
rejects bare strings (`"Jane Doe"`) — a clean cut with no `oneOf` compatibility
shim.

**Rationale:**
- Scholarly attribution (translator vs editor vs transcriber) was silently dropped
  when contributors were stored as plain strings.
- `config.json` already stored Spurgeon contributors as rich objects, but
  `spurgeon_mtp.py` flattened them on export — losing role/affiliation/url.
- Pre-launch is the cheapest time to migrate: few external consumers of the JSONL
  yet. Post-launch cost ≈ breaking every consumer.
- Single rich schema beats dual-field (`contributors` + `contributors_rich`);
  parallel fields drift.

**Migration scope:**
- All 8 v1 schemas updated.
- `schemas/types.ts` updated: `Contributor` interface + `ContributorRole` type.
- `build/validate.py` updated to use a `referencing.Registry` for `$ref` resolution.
- All parsers updated to emit `{"name": str}` objects (or pass-through rich objects
  for Spurgeon). The `_format_contributor` flatten in `spurgeon_mtp.py` was removed.
- Existing string contributors in `sources/*/config.json` are wrapped as
  `{"name": string}` at parse time — role/affiliation enrichment is a future pass.

**Deferred:** Re-running all parsers to regenerate `data/` files with object
contributors, and re-uploading to HuggingFace, is a separate operational step.
The schema and build pipeline are correct; regenerating outputs is follow-up work.

**HuggingFace gap window:** From 2026-04-23 until parsers are re-run, all
published JSONL records on HuggingFace still contain flat string contributors
(e.g. `"contributors": ["Philip Schaff"]`). This is schema-invalid under the
new definition. The gap closes when `build/run_all.sh` (or equivalent) is
re-executed and the output uploaded. Until then, downstream consumers reading
from HuggingFace should expect the old string format.

**References:**
- Plan: `plans/2026-04-23-contributors-schema-migration.md`
- Shared def: `schemas/v1/_defs/contributor.schema.json`
- Parser utility: `build/lib/contributors.py`
