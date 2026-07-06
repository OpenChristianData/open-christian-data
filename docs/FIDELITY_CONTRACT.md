# Fidelity contract

**Status:** Living document, seeded 2026-07-02 with the City of God pilot class (two renderings).
Further source classes are added as each format family is brought into the TEI IR — the class table
is written when the family is walked, not speculatively.

This is the oracle the fidelity gates check against. It rules, per source class and feature, what
must survive and where. "The goal is not to preserve everything, but to make every intentional loss
explicit, testable, and visible" (fidelity-IR plan, Codex-reviewed).

## The two boundaries

The pipeline is `raw source -> TEI IR -> projections` (ADR-0019). The two boundaries have different
rules:

1. **raw -> IR** is lossless by definition, except for features this contract explicitly tags
   `normalized` (deliberate canonicalization, recorded here once) or `excluded` (recorded here
   once, with the reason). The census-vs-TEI gate enforces this mechanically: every censused
   feature ID must appear in the IR or be covered by a `normalized`/`excluded` ruling.
2. **IR -> projection** may drop anything, but every drop appears on that projection's coverage
   ledger (`loss-receipt-v1`), per node ID. A drop absent from the ledger fails the build.

So the per-feature categories are:

- **preserve** — must exist in the IR, mapped to the named TEI carrier; absence fails the gate.
- **normalized** — transformed at raw->IR in a way recorded here (no per-instance provenance).
- **excluded** — not carried into the IR; the exclusion and its reason are recorded here. Reserved
  for artifacts of the digital container, never for content of the work.

## Class: CCEL ThML (City of God, `raw/ccel/npnf1/npnf102.xml`, div1 `iv`)

| Feature (census name) | Ruling | TEI carrier | Notes |
|---|---|---|---|
| Work scoping | preserve | one `<TEI>` per rendering | div1 `iv` only; volume front matter outside the div1 belongs to the NPNF volume, not this work |
| Books, chapters (`divisions_level2/3`) + titles | preserve | nested `<div type="book|chapter" n>` with `<head>` from `@title` | includes the Translator's Preface div2 (it has no div3 children; it is still content) |
| Paragraphs + source `@id` | preserve | `<p xml:id>` | IDs are source-derived, never minted where the source has one |
| Footnotes (`notes`) | preserve | `<note place="end" n xml:id>` inline at anchor | note bodies keep their internal markup (italics, lang spans) |
| Page breaks (`page_breaks`) | preserve | `<pb n xml:id>` | `@n` from ThML `@n`; the CCEL `href` page link is container navigation, not carried |
| Scripture refs (`scripture_refs`) | preserve + normalized | `<ref type="scripture" cRef>` with the raw text as element content | `@cRef` is OSIS via `build/lib/bible_ref_normalizer.py`; the raw form is never replaced, only annotated. Normalization: OSIS enrichment |
| Italics (`italics`) | preserve | `<hi rend="italic">` | ThML `<i>` is typographic; no ids in source (count-gated, not id-gated) |
| Language spans (`lang_spans`) | preserve + normalized | `@xml:lang` on `<foreign>` (inline runs) or the enclosing element | ThML codes map to BCP-47: `EL`->`grc`, `HE`->`he`, `LA`->`la`, `FR`->`fr`, `DE`->`de` (extend table as codes appear; unmapped codes fail loudly) |
| Work title page (`pb` + `p` runs directly under div1, before the first div2) | preserve | `<front><div type="title">` | found in the real file 2026-07-02: "The City of God / translated by / Rev. Marcus Dods, D.D." |
| Class-only display spans (`<span>` without `@lang`) | preserve | `<seg xml:id>` | CCEL styling hooks; text preserved, styling class not meaningful |
| Superscripts (`<sup>`) | preserve | `<hi rend="superscript">` | |
| Line breaks (`<br>`) | preserve | `<lb/>` | |
| DOCTYPE entities | normalized | resolved to Unicode at parse | same replacement set the JSON parser uses |
| Whitespace | normalized | XML-insignificant whitespace collapsed in prose | never inside `<hi>`/`<foreign>` boundaries in a way that changes visible text |
| CCEL `insertIndex`/`style`/`selector`/`scripContext` elements | excluded | — | ThML container/display machinery, not work content (the JSON parser's `_SKIP_TAGS` minus `note`/`pb`, which ARE content and are preserved above) |

## Class: Standard Ebooks XHTML (City of God, SE git clone, commit recorded in census)

| Feature (census name) | Ruling | TEI carrier | Notes |
|---|---|---|---|
| Nested `<section>` structure (`sections`, `section_depths`) incl. same-file chapters | preserve | nested `<div>` with `@type` from `epub:type` (`division`->`book`, `preface`, `chapter`) | this is the collapse the old JSON parser had; the census depth map is the gate |
| Heading labels/ordinals (h3/h4) | preserve | `<head>` | e.g. "Book I", roman numeral chapter heads |
| Bridgeheads (`bridgeheads`) | preserve | `<argument><p>` | SE encodes the chapter argument as `se:bridgehead`; TEI's `<argument>` is exactly this. The CCEL rendering carries the same sentence as `<head>` — per-source faithfulness, not forced sameness |
| Endnotes (`noterefs` + `endnotes`) | preserve | `<note place="end" n xml:id>` inlined at the anchor, body resolved from `endnotes.xhtml` | keep `note-N` id; noteref id recorded as `@corresp`; every noteref must resolve (census `unresolved_noterefs` must be empty) |
| Backlinks (`backlink` anchors in endnotes) | excluded | — | return-navigation artifact of the ebook container |
| Emphasis (`emphasis`) | preserve | `<em>` -> `<emph>`; `<i>` -> `<hi rend="italic">` | SE distinguishes semantic from typographic; TEI does too — keep the distinction |
| Verse quotations (`verse_blocks`) | preserve | `<quote><lg><l>` | SE `z3998:verse` blockquotes |
| Prose blockquotes | preserve | `<quote>` | |
| Language spans | preserve | `@xml:lang` (already BCP-47 in SE) | |
| Typographic/semantic inline spans | preserve | `abbr` -> `<abbr>`; `b` -> `<hi rend="bold">`; `cite` -> `<title>`; semantic `i`/`span` (se:name.*, z3998:*) -> `<hi rend="italic">`/`<seg>` with the epub:type kept in `@ana` as `se:<type>` | found in the real files 2026-07-02; the `@ana` value preserves the source's semantic claim without inventing TEI semantics for it |
| SE front/back matter (titlepage, imprint, colophon, uncopyright) | preserve | `<front>`/`<back>` divs | publisher wrapper of THIS edition; cheap to keep, and excluding it would be a silent loss of the rendering's actual content |
| `toc.xhtml` / nav documents | excluded | — | generated navigation, derivable from structure |
| CSS, images, fonts | excluded | — | presentation assets of the container (record in census as excluded file classes) |

## Class: Anglican liturgy (Book of Common Prayer HTML, 1549/1559/1662 full text + 1928 collects)

| Feature (census name) | Ruling | TEI carrier | Notes |
|---|---|---|---|
| Edition/rendering identity | preserve | one `<TEI>` per edition rendering; edition named in source metadata | 1549, 1559, 1662, and 1928 collects are distinct renderings of the BCP family |
| Service order (`services`) | preserve | `<div type="service" xml:id>` in source order | one service page or collect page group becomes one service/order node; order is a liturgical fact |
| Collect units (`collects`) | preserve | `<div type="collect" xml:id>` with `<label>` and prayer text | includes 1662/1928 collect labels and source-derived ids |
| Speaker/response structure (`speaker_units`) | preserve | `<sp xml:id><speaker>...` plus spoken `<p>` | do not leave Priest/Answer/Minister/People labels as undifferentiated prose when the source marks them |
| Rubrics (`rubrics`) | preserve | `<p rend="rubric" xml:id>` | red/italic instruction text, kneeling/standing directions, repetition notes, and service directives are content |
| Source labels (`labels`) | preserve | `<label xml:id>` or `<head>` | headings such as "The Collect.", canticle titles, psalm labels, and service section labels |
| Drop-cap image letters | normalized | Unicode text in the surrounding text node | the image is presentation; its `alt` letter is text and must be reconstructed |
| Italic/red display used only to mark rubrics | normalized | rubric classification on `<p rend="rubric">` | colour and font choice are presentation, not separately preserved |
| Navigation tables, source-site chrome, scripts, tracking blocks | excluded | — | digital container apparatus, not prayer-book content |
| Source-site editorial side notes | excluded | — | Justus narrow right-column notes are not the BCP text; do not mix them into liturgical order |

## Class: CCEL ThML (config-driven proof works: NPNF2 `npnf204` div1 `vii`; Owen `mort` div1 `i`)

Batch 06 extends the City of God CCEL pilot from a hard-coded div1 converter to a work-config-driven
converter. The proof set is deliberately representative, not exhaustive: Athanasius, *On the
Incarnation of the Word* (`ir/ccel/athanasius-on-the-incarnation.ccel-npnf204.tei.xml`) and John
Owen, *Of the Mortification of Sin in Believers*
(`ir/ccel/owen-mortification.ccel-owen-mort.tei.xml`). Remaining CCEL configs still require
per-work config and validation before they are treated as migrated.

| Feature (census name) | Ruling | TEI carrier | Notes |
|---|---|---|---|
| Work scoping | preserve | one `<TEI>` per configured work rendering | selected by `build/tei/ccel_work_configs.json`, not by converter code |
| Divisions (`divisions`) | preserve | nested `<div xml:id type>` | `type` comes from the work config: e.g. NPNF2 introduction/work/section; Owen preface/chapter |
| Paragraphs (`paragraphs`) | preserve | `<p xml:id>` | source IDs preserved; note-body paragraphs are carried inside notes but not counted as top-level paragraph census items |
| Footnotes (`notes`) | preserve | `<note place="end" n xml:id>` | inline at the source anchor |
| Page breaks (`page_breaks`) | preserve | `<pb n xml:id>` | `@n` from ThML; source navigation links remain container apparatus |
| Scripture refs (`scripture_refs`) | preserve + normalized where source data allows | `<ref type="scripture" cRef>` when `osisRef` or the normalizer can resolve it; otherwise `<ref type="scripture">` with raw text only | do not invent OSIS context for relative refs such as "verse 1" when the ThML lacks `osisRef` |
| Italics (`italics`) | preserve | `<hi rend="italic">` | count-gated; ThML italics do not always carry IDs |
| Language spans (`lang_spans`) | preserve + normalized | `<foreign xml:id xml:lang>` | ThML language codes map to BCP-47; unmapped codes fail loudly |
| Display spans (`display_spans`) | preserve | `<seg xml:id>` | class-only spans carry text and anchor identity, not CSS semantics |
| Arguments (`arguments`) | preserve | `<argument xml:id><p>...` | direct ThML argument text is wrapped in a TEI paragraph because TEI `argument` is element-only |
| Headings (`headings`) | preserve | `<head xml:id>` | source heading elements keep source IDs; division-title heads may also be generated from `@title` |
| Names (`names`) | preserve | `<name xml:id>` | source identity preserved without adding authority claims |
| Citations (`citations`) | preserve | `<title xml:id>` | ThML `<cite>` is bibliographic/title-like inline markup |
| Tables / rows / cells (`tables`, `table_rows`, `table_cells`) | preserve | `<table>`, `<row>`, `<cell>` | used by NPNF2 introductory material; IDs are gate-checked where the source supplies them |
| Work title pages / titlepage divisions | normalized or excluded by config | `<front>` when content belongs to the rendering; omitted when the work config marks a pure container titlepage skip | Owen `Titlepage` div is excluded in the proof config; NPNF2 Introduction is preserved as front matter |

## Projection defaults (all classes)

The HF training projection is clean faithful text only (maintainer decision, 2026-07-02 NSH
alignment): structure headings survive as text, `<argument>` survives as text; notes, page breaks,
`<ref>` annotations, emphasis markup, and front/back matter are dropped — every drop per node ID on
the coverage ledger. Other projections rule per-output; the ledger mechanism is identical.
