# tyerman-life-george-whitefield-vol-2-1877 — Project Gutenberg 62023

Status: source-bound, technically validated, nonaccepted TEI candidate. Human acceptance, applicable rights, and publication remain separate.

## Scope and exact authority

- Manifest row: L635; exact edition and volume scope: The Life of the Rev. George Whitefield, B.A. Vol. II.
- Retained archive SHA-256: `9f420e133c7d5f0ee2a1c6c09093039016609f22be8903f325efc42e8770a5e6`; 4 file members account for archive names/order, byte and compressed sizes, CRC-32, and each member digest.
- Text witness: `pg62023-images.html`, SHA-256 `24a3a6825397c9e4c9fb061bdbb865bb5cc6be455501ccc2c784a21efd0febfa`. Complete HTML head inventory and 24 ordered body carriers are profiled; body profile covers 19698 elements. All nontextual/support members remain retained and hash-accounted.
- Source manifest SHA-256: `14679063b733a4f268fc8ed9fc6ed736c7f3e63147780f958d72ba9130565eba`. Candidate package SHA-256: `8050e7d28bf241ad3cfe7c04fa4f6309813d1111900c1a17ccf966aaee88cc91`. Candidate review directory: `D:\Library\Open Christian Data\candidate-reviews\manifest-acquisition-20260925-tyerman-62023-v4`. Validation sidecar SHA-256: `3f471e4443d4ef5bdd14b7b69c2e85de773e565d0448760ea0a9c25f5f02d20e`, status `pass`, no findings.

## Reconstruction and independent checks

The readable TEI preserves the complete edition-specific body in source order. Project Gutenberg header/footer are assigned to front/back; all footer license text is retained as an explicit TEI wrapper. Source IDs, heading and paragraph sequences, inline renditions, page labels (including bare Roman and blank labels), links, lists, tables, image references, and wording are compared to archive-derived expectations. Table-contained layout divisions are represented with source-container milestones and readable paragraphs inside TEI cells. Volume boundaries are exact: each companion volume is a separate source and candidate; the third Wesley volume retains its included appendix and index.

Producer and oracle use different mapping/traversal implementations but share html5lib's HTML5 parser/recovery model; both re-read the exact retained archive. The oracle also binds ZIP CRC/member inventory, ordered HTML direct carriers, body text, structural signatures, candidate accountability, policy and rights README. Vendored TEI P5 validation passes. The shared parser assumption is recorded; print facsimile comparison remains separate.

## Challenge and reproduction

Baseline source oracle passes. 5 resealed source-feature mutations were each rejected for the intended paragraph, heading, link, inline, page-label, or table claim where available. The full candidate was regenerated from a fresh Python process with byte-identical manifest and members and passing validation. Receipt: `D:\Library\Open Christian Data\candidate-reviews\manifest-acquisition-20260925-tyerman-62023-v4\mutation-reproduction.json`, SHA-256 `a7100195dab72f4db866930a7c5979d84267d0071f59d4d7bfbb9be6b33e9bb4`.

No CVW/print-page visual review was performed. This is agent mechanical/source-text evidence and does not imply human acceptance or rights clearance.
