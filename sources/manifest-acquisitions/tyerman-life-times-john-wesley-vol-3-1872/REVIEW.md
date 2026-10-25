# tyerman-life-times-john-wesley-vol-3-1872 — Project Gutenberg 76882

Status: source-bound, technically validated, nonaccepted TEI candidate. Human acceptance, applicable rights, and publication remain separate.

## Scope and exact authority

- Manifest row: L634; exact edition and volume scope: The Life and Times of the Rev. John Wesley, M.A., Founder of the Methodists. Vol. III.
- Retained archive SHA-256: `7e3d35ea02e40d5bdfee8294ac4c3bd3316ce11c3322a06e687c2b6199824245`; 5 file members account for archive names/order, byte and compressed sizes, CRC-32, and each member digest.
- Text witness: `pg76882-images.html`, SHA-256 `a19097801543b108a6114e3c2aa9e0498d2d4bfdeef851b4052759ceed1cb1d9`. Complete HTML head inventory and 2308 ordered body carriers are profiled; body profile covers 17400 elements. All nontextual/support members remain retained and hash-accounted.
- Source manifest SHA-256: `fc070bfe0b347f43aff77d63d21ed64b028efdba344145d7c7d39a205acabdbd`. Candidate package SHA-256: `5cc59e991d150268fa0e32706006a31ad9cb2bbd9b83472526951a36764b7340`. Candidate review directory: `D:\Library\Open Christian Data\candidate-reviews\manifest-acquisition-20260925-tyerman-76882-v4`. Validation sidecar SHA-256: `2e7f4d17afe5e980058dc3838e2ee2e00765b8ab54e95a5db2b4f442de33bb4f`, status `pass`, no findings.

## Reconstruction and independent checks

The readable TEI preserves the complete edition-specific body in source order. Project Gutenberg header/footer are assigned to front/back; all footer license text is retained as an explicit TEI wrapper. Source IDs, heading and paragraph sequences, inline renditions, page labels (including bare Roman and blank labels), links, lists, tables, image references, and wording are compared to archive-derived expectations. Table-contained layout divisions are represented with source-container milestones and readable paragraphs inside TEI cells. Volume boundaries are exact: each companion volume is a separate source and candidate; the third Wesley volume retains its included appendix and index.

Producer and oracle use different mapping/traversal implementations but share html5lib's HTML5 parser/recovery model; both re-read the exact retained archive. The oracle also binds ZIP CRC/member inventory, ordered HTML direct carriers, body text, structural signatures, candidate accountability, policy and rights README. Vendored TEI P5 validation passes. The shared parser assumption is recorded; print facsimile comparison remains separate.

## Challenge and reproduction

Baseline source oracle passes. 5 resealed source-feature mutations were each rejected for the intended paragraph, heading, link, inline, page-label, or table claim where available. The full candidate was regenerated from a fresh Python process with byte-identical manifest and members and passing validation. Receipt: `D:\Library\Open Christian Data\candidate-reviews\manifest-acquisition-20260925-tyerman-76882-v4\mutation-reproduction.json`, SHA-256 `d8ba5a53a69d5c9ca0cbe27977981d8d5a86285627cda73e0efc84bb5e91b774`.

No CVW/print-page visual review was performed. This is agent mechanical/source-text evidence and does not imply human acceptance or rights clearance.
