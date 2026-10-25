# Current-runtime reconstruction fixtures

The Spurgeon manifest is a test-only derivative of
`sources/spurgeon-mtp/spurgeon-mtp.source-manifest.json` at SHA-256
`12ccaf17790f0916048a679c3bb985efa5221f9c424ae9c3ec10101eda1c8e7a`.

It preserves every retained member, source hash, profile, scope, attribution,
and exclusion. Its only changes bind the staged reconstruction contract,
the oracle's explicit import-path update, and that oracle's verified import
closure. The historical manifest, accepted master, and historical receipts
remain unchanged.

`test_runtime_fixture_preserves_retained_inputs_and_only_updates_changed_dependencies`
checks that exact boundary. Rebuild the local, nonaccepted candidate using
the command in `docs/AGENT_TESTING.md` before running the complete LIB-084
tests. Candidate payloads stay outside Git.

The NPNF105 fixture preserves the historical manifest at SHA-256
`fc1824fc52a968aff16cdfe42246a1f69fa3d3e2cd659d82aefbbf98dfd50d12`.
It binds the current validator implementation and import closure. The validator
checks member metadata before compiling the unchanged complete XML schema.
Retained source authorities, converter, canonical manifest, and historical
receipts stay unchanged. Its test compares the complete records after only
those two runtime updates.

The John Owen LIB-052 fixture similarly preserves the historical manifest at
SHA-256 `ccd09869a9f1c04d01b21c43c3393393156bca2239ef2207e8bc2209585b1a15`.
Only its validator import-closure digest changes for the current shared
contract. A complete-record equality test enforces that boundary.

`l225_ebible_usfm.py` preserves the exact historical dependency retained at
`reports/_logs/engwebpb-existing-install-20261003-v1/historical-shared-dependency/build/tei/l225_ebible_usfm.py`,
SHA-256 `68d72bd48ff27ba54b374339e52b7259fdd00bdfb41ae31e85c10c9296f17ccc`.
The focused semantic-inline test checks that digest and loads this source only
in its isolated historical import context; no canonical dependency is restored.

The remaining runtime fixtures follow the same boundary. Their frozen source
hashes and exact permitted differences are checked in the matching focused
tests. `missing-baseline-bindings.json`, `runtime-binding-cases.json`,
`closure-baselines.json`, and `newline-binding-cases.json` record the original
authorities and runtime-only updates for their groups. Clarke and Luther have
explicit preservation checks in their existing contract tests.

Historical attribution notices and owner maps under `authorities/` and
`hodge-vol2.README.source.md` are exact byte copies matching the original
manifest hashes. Their current canonical successors are preserved separately.
The Pilgrim profile and NPNF113 closure descriptor change only the explicitly
tested runtime fields. Line-ending fixtures prove that the historical
implementation hashes describe CRLF versions of the current LF source.

These are test authorities, not replacements for the historical source
manifests, acceptance records, or publication approvals. Canonical closure
audits continue to expose stale historical runtime bindings; the test gate
requires a pinned, separately verified current-runtime successor for each
accounted-for mismatch.

`retained-manifest-inventory.json` records every retained source manifest.
This proves conservation, not current runtime compatibility. Historical,
intentionally corrupted, and superseded records remain visible to the
production auditor, which continues reporting unsupported or stale routes.

`maintained-closure-routes.json` lists current-runtime test fixtures and their
complete-record preservation tests. Membership must exactly match the explicit
fixture-group metadata. Every registered validator and declared producer
closure must match its route-owned implementation. Canonical validators also remain checked independently in
`canonical-live-validator-bindings.json`. When shared code changes, its frozen
canonical records remain unchanged. `canonical-live-runtime-successors.json`
selects test-only successors under `canonical-live/`; the same test compares
each complete record with its original, permits only the validator closure to
change, and verifies the current closure independently.

Historical support copies in `runtime-binding-cases.json` preserve exact
original byte/hash pins. No test repair reaccepts a historical package,
modifies a retained master, or clears publication.

`individual-runtime-bindings.json` and the three `next-binding-*.json`
inventories account for additional maintained test callers. Their preservation
tests freeze the original complete records, update only declared runtime
bindings, and retain exact historical notices when the canonical notice has
since changed. Runtime profiles preserve every field except their producer
closure; LIB-038's two structured closure authorities preserve the original
member paths and bind their current bytes.

Candidate-evidence catalog tests select the exact retained data claims and
their explicit runtime test manifest. The separate live catalog tests retain
the complete library inventory and canonical route checks.
