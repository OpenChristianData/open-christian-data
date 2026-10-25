# Aquinas, *Summa Theologica* — four Project Gutenberg components

This source-local route reconstructs one provisional English *Summa Theologica* source-upgrade candidate from four exact Project Gutenberg HTML packages. The retained expression is translated by the Fathers of the English Dominican Province and identifies itself as the Complete American Edition / Benziger Brothers, New York. It is not a new canonical work identity and does not alter the repository's other Aquinas material.

## Exact retained components

| Order | PG ID | Component | Questions | Terminal boundary | HTML SHA-256 |
|---:|---:|---|---:|---|---|
| 1 | 17611 | Part I, *Prima Pars* | 1–119 | I, Q.119, Art.2; `id07860` | `48421f1cb257f450c16844168f5cbb5f328b7825a9387ef670b81b53c3403195` |
| 2 | 17897 | Part I–II, *Prima Secundae* | 1–114 | I–II, Q.114, Art.10; `id08135` | `669cecdd59450d256650be9d6af3f2577926af19276f16eef80e4b986bb8fc93` |
| 3 | 18755 | Part II–II, *Secunda Secundae* | 1–189 | Q.189, Art.10; `id12081` | `c1fa4ed1dbaa01c9cb3658d9eec0241b51a1848c4f84bf779734ba4d2935ef18` |
| 4 | 19950 | Part III, *Tertia Pars* | 1–90 | III, Q.90, Art.4; `id07408` | `2115def3be1b02480329147caddde90cd16d378db1e13c427f904aa12fba9671` |

Official records: <https://www.gutenberg.org/ebooks/17611>, <https://www.gutenberg.org/ebooks/17897>, <https://www.gutenberg.org/ebooks/18755>, and <https://www.gutenberg.org/ebooks/19950>. Each exact HTML ZIP, landing page, RDF record, and response header capture is retained under `raw/clean-ready-acquisition-to-tei/master-1/09/aquinas-summa-theologica-four-parts/`. The four archives contain exactly one HTML member and one cover image each. The 24 retained raw files and eight archive members are bound by the acquisition receipt; their canonical listing digest is `3b12abbc39fe1435d04917ad4e3c864f7973ab9826d1370cbc7f0f7f591aff9e`.

## Fidelity and accounting

The candidate retains 35,488 source units in exact component and source-ID order. It encodes 512 questions and 2,669 semantic articles: 119/584, 114/619, 189/917, and 90/549 by component. Per-component normalized visible-text SHA-256 values are identical between retained HTML and TEI. The validator also binds every source-unit ID, contents and prologue boundaries, question/article positions, terminal text, 7,962 italic spans, 2,961 explicit line breaks, local analysis references, and the absence of invented print-page milestones.

The retained electronic edition's dedication, contents, prologues, question/article numbering, corrections, bracketed notes, transliterated Greek, emphasis, quotation conventions, and Part-III insertion are preserved as source evidence. Omitted print pagination, print headers, repetitive article formulae, and other absent print features are not reconstructed. The Project Gutenberg header/footer wrappers remain in the exact HTML packages but are explicitly excluded from TEI text.

Observed source anomalies are preserved and accounted for rather than silently corrected. These include omitted question headings (I Q116; I–II Q1; II–II Q183), two implicit one-article headings in Part I, the mislabeled duplicate QUESTION 23 at I–II `id01743`, the I–II Q38 “Four Articles” descriptor followed by five inquiries and five articles, the bare SIXTH ARTICLE at II–II `id01741`, four unnumbered II–II article labels, the literal `Q. 811` typo at `id11244`, and the Part-III electronic editorial insertion `id01912`–`id01941` between Questions 26 and 27.

## Validation and visual boundary

The ticket-local suite passes all six tests, including serialized TEI Relax NG validation, exact projection checks, seeded omission/reordering/italic/line-break failures, same-output rejection, and two fresh-process byte-identical conversions. Sixteen compact visual pairs compare the exact retained HTML DOM with the existing CETEIcean verification viewer at the opening, a middle question transition, the terminal boundary, and one unusual feature for each component. Exact anchor text is equal on both sides; the four contact sheets were inspected. This is technical spot verification only, not page-by-page or human textual acceptance.

The repository fast suite could not establish a whole-repository pass from this isolated worktree because hundreds of unrelated source-dependent tests require retained `raw/` paths not exposed here. Its observed result was 2,334 passed, 116 skipped, 10 xfailed, 52 failed, and 599 collection/setup errors. The ticket-local source route remained green.

## Rights, exclusions, and status

Each retained official RDF/landing record states `Public domain in the USA.` and links the Project Gutenberg license/public-domain metadata. That statement is jurisdiction-specific; users outside the USA must make their own rights determination. The Project Gutenberg name/trademark and redistribution license are distinct from the underlying text's copyright status, and the retained wrappers remain the authority for those terms.

No Supplement or fifth component is present or claimed. This is not the complete traditional five-component *Summa*. CCEL, prior OCR, other Aquinas commentary data, and other Gutenberg editions were not acquisition authorities. Canonical `data/`, `ir/`, WorkCatalog, schemas, kernel, acceptance, publication, commit, and push are untouched.
