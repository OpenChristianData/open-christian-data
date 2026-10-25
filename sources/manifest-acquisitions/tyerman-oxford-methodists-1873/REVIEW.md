# tyerman-oxford-methodists-1873 — Project Gutenberg 70497

Status: source-bound, technically validated, nonaccepted TEI candidate. Human acceptance, applicable rights, and publication remain separate.

## Scope and exact authority

- Manifest row: L636; exact edition and volume scope: The Oxford Methodists.
- Retained archive SHA-256: `016911839d5e043caddacae2206a06328d0e44e6c112dc1b7dce59e7b6cf9441`; 5 file members account for archive names/order, byte and compressed sizes, CRC-32, and each member digest.
- Text witness: `pg70497-images.html`, SHA-256 `957c0933cc515d69574bde25938cccc6a7b01b669c816e4aa8187d9f857f52df`. Complete HTML head inventory and 1316 ordered body carriers are profiled; body profile covers 7984 elements. All nontextual/support members remain retained and hash-accounted.
- Source manifest SHA-256: `7615e81647e9480c96fa3bb79b46eb89f8ff61290d1e81f2ac5e6f863a88a7c9`. Candidate package SHA-256: `e350269698d18ec87727559ade305f0e6130963662d0111d852618cd6623e17a`. Candidate review directory: `D:\Library\Open Christian Data\candidate-reviews\manifest-acquisition-20260925-tyerman-70497-v4`. Validation sidecar SHA-256: `447bbf067cd62f3ca45a5876c706ef1558e939b1bb1527b3a0567b9232178aea`, status `pass`, no findings.

## Reconstruction and independent checks

The readable TEI preserves the complete edition-specific body in source order. Project Gutenberg header/footer are assigned to front/back; all footer license text is retained as an explicit TEI wrapper. Source IDs, heading and paragraph sequences, inline renditions, page labels (including bare Roman and blank labels), links, lists, tables, image references, and wording are compared to archive-derived expectations. Table-contained layout divisions are represented with source-container milestones and readable paragraphs inside TEI cells. Volume boundaries are exact: each companion volume is a separate source and candidate; the third Wesley volume retains its included appendix and index.

Producer and oracle use different mapping/traversal implementations but share html5lib's HTML5 parser/recovery model; both re-read the exact retained archive. The oracle also binds ZIP CRC/member inventory, ordered HTML direct carriers, body text, structural signatures, candidate accountability, policy and rights README. Vendored TEI P5 validation passes. The shared parser assumption is recorded; print facsimile comparison remains separate.

## Challenge and reproduction

Baseline source oracle passes. 5 resealed source-feature mutations were each rejected for the intended paragraph, heading, link, inline, page-label, or table claim where available. The full candidate was regenerated from a fresh Python process with byte-identical manifest and members and passing validation. Receipt: `D:\Library\Open Christian Data\candidate-reviews\manifest-acquisition-20260925-tyerman-70497-v4\mutation-reproduction.json`, SHA-256 `767ea82c6fd8d4bccad4fba5f1b1543f1b42f83a1cb01faa9633f103e4349f08`.

No CVW/print-page visual review was performed. This is agent mechanical/source-text evidence and does not imply human acceptance or rights clearance.

## Canonical Workspace recheck (2026-09-30)

The current Workspace source manifest and its bound shared converter/oracle were rechecked against the retained Gutenberg archive and source authorities. Two independent fresh Python processes reran conversion and P5/oracle validation in memory; both reproduced the persisted v4 package manifest, all five package members, and validation sidecar byte-for-byte with no findings. The complete current evidence receipt is `plans/2026-09-23-acquisition-manifest-source-to-tei/L636_TYERMAN_OXFORD_METHODISTS_CURRENT_TECHNICAL_RECEIPT_20260930.json` (SHA-256 `5844685d1d5ce94663bb2ad092d4edee4fe62dd921a4849fb9a219cc75f85238`). The candidate remains nonaccepted. No CVW/print-page review, human acceptance, rights clearance, or publication authorization is claimed.
