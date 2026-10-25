# tyerman-life-times-john-wesley-vol-2-1872 — Project Gutenberg 71130

Status: source-bound, technically validated, nonaccepted TEI candidate. Human acceptance, applicable rights, and publication remain separate.

## Scope and exact authority

- Manifest row: L634; exact edition and volume scope: The Life and Times of the Rev. John Wesley, M.A., Founder of the Methodists. Vol. II.
- Retained archive SHA-256: `0dd3ef53f9081c06cb604c052748cb155ae1100e52720961472e387421bfe062`; 4 file members account for archive names/order, byte and compressed sizes, CRC-32, and each member digest.
- Text witness: `pg71130-images.html`, SHA-256 `bb9af7cb52d4c42e08461ccb5fafe042f9c0993edd902397fc0d2d8248395b3f`. Complete HTML head inventory and 2045 ordered body carriers are profiled; body profile covers 9914 elements. All nontextual/support members remain retained and hash-accounted.
- Source manifest SHA-256: `d99f4941d0ed0d12ff6533c071c7bb5b4e5fa964070980c857518f2069c6b185`. Candidate package SHA-256: `d06d98841ffbaea8d184d77ba605e39e97ca288a37e5c9787476f0cdcc175819`. Candidate review directory: `D:\Library\Open Christian Data\candidate-reviews\manifest-acquisition-20260925-tyerman-71130-v4`. Validation sidecar SHA-256: `05bb937835ed0cfb718509c1e4c8a64f1f66bf42a36d6b38bb28ec0436f3dd0b`, status `pass`, no findings.

## Reconstruction and independent checks

The readable TEI preserves the complete edition-specific body in source order. Project Gutenberg header/footer are assigned to front/back; all footer license text is retained as an explicit TEI wrapper. Source IDs, heading and paragraph sequences, inline renditions, page labels (including bare Roman and blank labels), links, lists, tables, image references, and wording are compared to archive-derived expectations. Table-contained layout divisions are represented with source-container milestones and readable paragraphs inside TEI cells. Volume boundaries are exact: each companion volume is a separate source and candidate; the third Wesley volume retains its included appendix and index.

Producer and oracle use different mapping/traversal implementations but share html5lib's HTML5 parser/recovery model; both re-read the exact retained archive. The oracle also binds ZIP CRC/member inventory, ordered HTML direct carriers, body text, structural signatures, candidate accountability, policy and rights README. Vendored TEI P5 validation passes. The shared parser assumption is recorded; print facsimile comparison remains separate.

## Challenge and reproduction

Baseline source oracle passes. 5 resealed source-feature mutations were each rejected for the intended paragraph, heading, link, inline, page-label, or table claim where available. The full candidate was regenerated from a fresh Python process with byte-identical manifest and members and passing validation. Receipt: `D:\Library\Open Christian Data\candidate-reviews\manifest-acquisition-20260925-tyerman-71130-v4\mutation-reproduction.json`, SHA-256 `95dc95ad944a413b354c04a2b6462e4106eaf89b2d8d133e4e1b96b4d6f20d07`.

No CVW/print-page visual review was performed. This is agent mechanical/source-text evidence and does not imply human acceptance or rights clearance.
