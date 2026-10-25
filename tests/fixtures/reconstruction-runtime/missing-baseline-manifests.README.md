# Missing historical test aliases

The manifests listed in `missing-baseline-bindings.json` replace missing dated
test-only aliases. Each starts from the named canonical manifest, whose exact
SHA-256 is frozen in that registry. Retained source members, profiles, policies,
scope, and attribution records remain identical. Only the current implementation
hashes, their runtime authority bindings, and the oracle import closure change.
`test_missing_baseline_runtime_manifests.py` compares every complete record.

The Hodge volume 2 test also relocates its historical attribution authority to
`hodge-vol2.README.source.md`. That file preserves the exact 1,780 bytes and
SHA-256 from the original manifest and retained package. The canonical source
notice includes later rights work and remains untouched. This historical fixture
does not replace current rights guidance or establish acceptance or publication.

These are technical reconstruction fixtures. They do not change canonical
manifests, accepted masters, source rights, or release approval.
