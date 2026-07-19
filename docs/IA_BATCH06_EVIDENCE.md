# Batch 06 Internet Archive evidence

This record covers the Fisher Marrow raw-to-TEI migration and the three
evidence-only decisions in the batch. The Fisher converter reads the raw
DjVuTXT witness directly. The existing structured-text JSON is a downstream
projection and was not used as conversion input.

## Fisher Marrow of Modern Divinity

Raw witness: `raw/internet-archive/fisher-marrow/marrowmoderndiv00bostgoog_djvu.txt`

- SHA-256: `14b46f1a400f8e2c8ec7612019a7769dac46daf31e10f7d6b68212351ff46dd3`
- Source: Google Books DjVuTXT, ABBYY OCR, Internet Archive item
  `marrowmoderndiv00bostgoog`.
- Census scope starts at raw line 1285, `INTRODUCTION.`. The raw witness has
  22,946 newline-delimited segments and 22,945 newline characters; it has no
  form-feed page breaks.
- OCR classification: `ocr-raw-english-prose`. The selected scope has 0 Greek
  code points and 0 Hebrew code points. No table carrier was observed.
- Inline evidence: `*` occurs 2,039 times on 1,758 lines; `§` occurs 44 times
  on 44 lines; `†` and `‡` do not occur. The asterisks and section marks are
  retained as source text. The witness does not reliably delimit Boston
  footnote bodies, so no `<note>` boundaries are invented.

The raw heading forms are not normalized: the four chapter headings are
`CHAPTER I.`, `CHAPTER TL`, `CHAPTER III.`, and `CHAP. LV.` (one each). The
eight commandment headings are `COMMANDMENT I,`, `COMMANDMENT IF.`,
`COMMANDMENT HI,`, `COMMANDMENT IV-`, `COMMANDMENT VI.`, `COMMANDMENT VHI.`,
`COMMANDMENT IX.`, and `COMMANDMENT X.` (one each). The 47 section-prefixed
lines break down as `sect.` 27, `sect*` 5, `sect,` 7, `sect-` 7, and one
`section` form. This includes damaged forms such as `sect, vit ...` and
`SECT* U.—Of THB Promibis.`; they are retained in the census rather than
silently folded into a canonical spelling. Six long synopsis lines are kept as
prose, including the unusual line beginning `Sect, L — Christ's ...` whose
second dash could otherwise be mistaken for a new boundary. The speaker
census records 82 exact OCR label-plus-punctuation forms, including variants
such as `Norn`, `AnL`, `iVeo`, `JVeo`, `JVbm`, `iVom`, `N^eo`, `^eo`, `iVffo`,
`N^o`, `&an`, and `Łvan`, in addition to the familiar labels.

Raw structural census and TEI carriers agree as follows:

| Carrier | Raw census | TEI |
|---|---:|---:|
| Parts | 2 (Part I inferred from the body and Part Second explicit) | 2 `div[@type="part"]` |
| Chapter headings | 4 | 4 `div[@type="chapter"]` |
| Commandment headings | 8 | 8 `div[@type="commandment"]` |
| All `Sect`-prefixed lines | 47 | — |
| Structural section boundaries | 41 | 41 `div[@type="section"]` |
| Section synopsis lines | 6 | 6 `p[@rend="section-synopsis"]` |
| High-confidence dialogue labels | 455 | 455 `sp` + 455 `speaker` |
| Ambiguous speaker-like starts left as prose | 123 | 123 not promoted by the classifier |
| Page breaks | 0 | 0 `pb` |

OCR heading evidence is kept verbatim in the TEI, including `CHAPTER TL`,
`CHAP. LV.`, `COMMANDMENT IF.`, and `COMMANDMENT VHI.`. Missing standalone
`COMMANDMENT III` and `COMMANDMENT V` headings are not fabricated. The
classifier promotes only bounded high-confidence speaker forms; heavily
damaged or ambiguous starts remain ordinary paragraphs.

## Evidence-only decisions

### `ia-ocr-general` — `tei-later`

The family currently covers 10 general text/PDF parser routes. It is
heterogeneous, and no single raw witness was selected for a bounded migration
in this batch. A family-wide structure or OCR-quality count would therefore
be misleading. The existing outputs carry parser-specific plain text and
local structures, but do not establish a uniform family carrier model.
Preserve the MANIFEST `OCR-GOOD`/`OCR-RAW` split and census each work before
choosing TEI carriers. No TEI carrier counts are asserted here.

### `ia-hastings-dictionary` — `tei-later`

The source config names 5 raw volume files: volumes 1–4 plus an extra volume.
The current downstream output has 2,512 entries, 835 See/See-also related-term
links across 479 entries, and 0 entries with `scripture_references`. Those are
evidence about the current parser projection, not a raw-to-TEI census. A
headword-by-headword raw census is required before selecting headword,
cross-reference, and OCR apparatus carriers. No TEI migration was performed.

### `ia-schaff-herzog-legacy` — `do-not-migrate`

The resident legacy parser output contains 8,351 combined reference entries.
That route is frozen and superseded. New Schaff-Herzog OCR rendering and
sidecar artifacts are outside this dataset repository and belong to the
separate OCR project; they are not part of this batch. Do not create a new TEI
migration from the legacy combined JSON route. Any future publication work
must use the upstream OCR/rendering lane and its provenance model.
