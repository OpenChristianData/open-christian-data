# tyerman-life-times-samuel-wesley-1866 — Project Gutenberg 67980

Status: source-bound, technically validated, nonaccepted TEI candidate. Human acceptance, applicable rights, and publication remain separate.

## Scope and exact authority

- Manifest row: L637; exact edition and volume scope: The Life and Times of the Rev. Samuel Wesley, M.A..
- Retained archive SHA-256: `a745273a2a6d5bdc0b036cb2b946dc9440b58edf74e6ff24ed8e700ee6995fc7`; 3 file members account for archive names/order, byte and compressed sizes, CRC-32, and each member digest.
- Text witness: `pg67980-images.html`, SHA-256 `98cca9b96a0e81ef16fc4409c2a37b6baba20ee64527456616670f7f3f906094`. Complete HTML head inventory and 1806 ordered body carriers are profiled; body profile covers 10589 elements. All nontextual/support members remain retained and hash-accounted.
- Source manifest SHA-256: `93fa1865009015fa141180573ec54d568c429f7fe09ef1af44685b652d0a5036`. Candidate package SHA-256: `aee7d82a4fe8d29a3ce5194e3d140c6089255187bd8d0586a3e7616993803a9d`. Candidate review directory: `D:\Library\Open Christian Data\candidate-reviews\manifest-acquisition-20260925-tyerman-67980-v4`. Validation sidecar SHA-256: `fcbe16072407e2931bc6234237ca6ef2d2b049aaa529782fbe009e7f3de773ae`, status `pass`, no findings.

## Reconstruction and independent checks

The readable TEI preserves the complete edition-specific body in source order. Project Gutenberg header/footer are assigned to front/back; all footer license text is retained as an explicit TEI wrapper. Source IDs, heading and paragraph sequences, inline renditions, page labels (including bare Roman and blank labels), links, lists, tables, image references, and wording are compared to archive-derived expectations. Table-contained layout divisions are represented with source-container milestones and readable paragraphs inside TEI cells. Volume boundaries are exact: each companion volume is a separate source and candidate; the third Wesley volume retains its included appendix and index.

Producer and oracle use different mapping/traversal implementations but share html5lib's HTML5 parser/recovery model; both re-read the exact retained archive. The oracle also binds ZIP CRC/member inventory, ordered HTML direct carriers, body text, structural signatures, candidate accountability, policy and rights README. Vendored TEI P5 validation passes. The shared parser assumption is recorded; print facsimile comparison remains separate.

## Challenge and reproduction

Baseline source oracle passes. 4 resealed source-feature mutations were each rejected for the intended paragraph, heading, link, inline, page-label, or table claim where available. The full candidate was regenerated from a fresh Python process with byte-identical manifest and members and passing validation. Receipt: `D:\Library\Open Christian Data\candidate-reviews\manifest-acquisition-20260925-tyerman-67980-v4\mutation-reproduction.json`, SHA-256 `a74f19f4a56712c9119aea2b93f85cb6306f3a87d905ec6f6dc9f39b62fdc509`.

No CVW/print-page visual review was performed. This is agent mechanical/source-text evidence and does not imply human acceptance or rights clearance.
