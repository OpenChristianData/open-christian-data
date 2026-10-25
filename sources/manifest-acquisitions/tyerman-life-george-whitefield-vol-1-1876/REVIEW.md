# tyerman-life-george-whitefield-vol-1-1876 — Project Gutenberg 44280

Status: source-bound, technically validated, nonaccepted TEI candidate. Human acceptance, applicable rights, and publication remain separate.

## Scope and exact authority

- Manifest row: L635; exact edition and volume scope: The Life of the Rev. George Whitefield, B.A. Vol. I.
- Retained archive SHA-256: `e20db686be152c089ebbaae0cd41c7bcc92c42953bc5d4d7f3a2a12075bcf8bf`; 3 file members account for archive names/order, byte and compressed sizes, CRC-32, and each member digest.
- Text witness: `pg44280-images.html`, SHA-256 `8b1f346c952efe26f71c259fd08ebcbe38097a03eeeeae41d8f3c0cf556e0aca`. Complete HTML head inventory and 2195 ordered body carriers are profiled; body profile covers 11533 elements. All nontextual/support members remain retained and hash-accounted.
- Source manifest SHA-256: `60348b2e4ad6d5f7b33aca2447c3930fd3be2ed4de4aeb2c9298839cdc989a28`. Candidate package SHA-256: `40800187045cd202e10d57f675be53353db9bd7fe6bdd3584c208d91dda4fa04`. Candidate review directory: `D:\Library\Open Christian Data\candidate-reviews\manifest-acquisition-20260925-tyerman-44280-v4`. Validation sidecar SHA-256: `ed6e8850913ab2221b3bb9ba6a33e9e4e404c7e3b07c2b02a12e7ce04c9043cc`, status `pass`, no findings.

## Reconstruction and independent checks

The readable TEI preserves the complete edition-specific body in source order. Project Gutenberg header/footer are assigned to front/back; all footer license text is retained as an explicit TEI wrapper. Source IDs, heading and paragraph sequences, inline renditions, page labels (including bare Roman and blank labels), links, lists, tables, image references, and wording are compared to archive-derived expectations. Table-contained layout divisions are represented with source-container milestones and readable paragraphs inside TEI cells. Volume boundaries are exact: each companion volume is a separate source and candidate; the third Wesley volume retains its included appendix and index.

Producer and oracle use different mapping/traversal implementations but share html5lib's HTML5 parser/recovery model; both re-read the exact retained archive. The oracle also binds ZIP CRC/member inventory, ordered HTML direct carriers, body text, structural signatures, candidate accountability, policy and rights README. Vendored TEI P5 validation passes. The shared parser assumption is recorded; print facsimile comparison remains separate.

## Challenge and reproduction

Baseline source oracle passes. 6 resealed source-feature mutations were each rejected for the intended paragraph, heading, link, inline, page-label, or table claim where available. The full candidate was regenerated from a fresh Python process with byte-identical manifest and members and passing validation. Receipt: `D:\Library\Open Christian Data\candidate-reviews\manifest-acquisition-20260925-tyerman-44280-v4\mutation-reproduction.json`, SHA-256 `7cff2f898af2377589710266419da8e7302781bf91d2b016eb5fa56900b6c7a6`.

No CVW/print-page visual review was performed. This is agent mechanical/source-text evidence and does not imply human acceptance or rights clearance.
