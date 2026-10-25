# tyerman-life-times-john-wesley-vol-1-1872 — Project Gutenberg 69582

Status: source-bound, technically validated, nonaccepted TEI candidate. Human acceptance, applicable rights, and publication remain separate.

## Scope and exact authority

- Manifest row: L634; exact edition and volume scope: The Life and Times of the Rev. John Wesley, M.A., Founder of the Methodists. Vol. I.
- Retained archive SHA-256: `fd78f98a6b79186a5f886c2e0f49a30c4b6d2ab9eae59c43d49e5f582898bf8b`; 4 file members account for archive names/order, byte and compressed sizes, CRC-32, and each member digest.
- Text witness: `pg69582-images.html`, SHA-256 `2ad42d6e11aff887687442845cabd8079248359c10fc0331cc440dd5c6cd6354`. Complete HTML head inventory and 1882 ordered body carriers are profiled; body profile covers 7267 elements. All nontextual/support members remain retained and hash-accounted.
- Source manifest SHA-256: `39efc17caa95bcf03c232f1a268f39881f7b7c714619fd2e71af0b46adb2ddaa`. Candidate package SHA-256: `aae5910ea9927b60b18169689159b0678d144224519718d61278da703ad146ae`. Candidate review directory: `D:\Library\Open Christian Data\candidate-reviews\manifest-acquisition-20260925-tyerman-69582-v4`. Validation sidecar SHA-256: `754a9e61a9da44bfdf5ea1ea420096c6a08432f1436183092146389db9ae40c5`, status `pass`, no findings.

## Reconstruction and independent checks

The readable TEI preserves the complete edition-specific body in source order. Project Gutenberg header/footer are assigned to front/back; all footer license text is retained as an explicit TEI wrapper. Source IDs, heading and paragraph sequences, inline renditions, page labels (including bare Roman and blank labels), links, lists, tables, image references, and wording are compared to archive-derived expectations. Table-contained layout divisions are represented with source-container milestones and readable paragraphs inside TEI cells. Volume boundaries are exact: each companion volume is a separate source and candidate; the third Wesley volume retains its included appendix and index.

Producer and oracle use different mapping/traversal implementations but share html5lib's HTML5 parser/recovery model; both re-read the exact retained archive. The oracle also binds ZIP CRC/member inventory, ordered HTML direct carriers, body text, structural signatures, candidate accountability, policy and rights README. Vendored TEI P5 validation passes. The shared parser assumption is recorded; print facsimile comparison remains separate.

## Challenge and reproduction

Baseline source oracle passes. 5 resealed source-feature mutations were each rejected for the intended paragraph, heading, link, inline, page-label, or table claim where available. The full candidate was regenerated from a fresh Python process with byte-identical manifest and members and passing validation. Receipt: `D:\Library\Open Christian Data\candidate-reviews\manifest-acquisition-20260925-tyerman-69582-v4\mutation-reproduction.json`, SHA-256 `b584c25de2f4d7d4d22a3ba663c47c632dfa87ef1995c9e69fe644a5fb5d9a2e`.

No CVW/print-page visual review was performed. This is agent mechanical/source-text evidence and does not imply human acceptance or rights clearance.
