# Fidelity contract

**Status:** Living document, seeded 2026-07-02 with the City of God pilot class (two renderings).
Further source classes are added as each format family is brought into the TEI IR — the class table
is written when the family is walked, not speculatively. The 2026-07-16 campaign expanded the named
proof set but performed no publish cutover. Unresolved fidelity and cutover work lives in
`docs/DATASET_SUCCESSOR_QUEUE.md`.

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
2. **IR -> projection** may drop anything, and the intended contract is that every drop appears on
   that projection's coverage ledger (`loss-receipt-v1`), per node ID. The present checker enforces
   node accounting and verifies text only when a target carries character spans; it does not prove
   that every node classified as projected contributed its text.

> **Integrity warning (2026-07-16): a ledger PASS is necessary, not sufficient.** The BCP-1549
> ledger reports `dropped: 0`, `normalized: 0`, and 332 projected labels while 287 of those label
> texts are absent from output. Earlier PASS results in this document remain valid accounting
> results, and their independent census/carrier/viewer evidence still stands, but the ledger alone
> cannot certify fidelity until the P1 successor fix lands. Nothing was cut over or published.

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

## Class: Standard Ebooks XHTML (Batch 05 accepted renderings: Bunyan and Kempis)

The Batch 05 census is deliberately source-specific: the existing City of God contract remains
unchanged, while these renderings add carriers that the pilot did not exercise.

| Feature (census name) | Ruling | TEI carrier | Notes |
|---|---|---|---|
| Additional section vocabulary (`appendix`, `dedication`, `epigraph`, `foreword`, `introduction`, `preamble`, `z3998:subchapter`) | preserve | `<div type>` | Map the source token to the TEI type without flattening its nesting. |
| Bare `bridgehead` paragraphs | preserve | `<argument><p>` | Kempis uses the bare token rather than `se:bridgehead`; it remains a chapter-level argument carrier. |
| `hgroup` headings | preserve | `<head>` | Preserve the heading text and source identity while normalizing the XHTML heading wrapper. |
| Semantic and typographic emphasis (`em`, `i`, `b`, `strong`) | preserve | `<emph>` or `<hi rend="italic|bold">` | Keep semantic `<em>` distinct from typographic `<i>`; bold elements normalize to TEI bold. |
| Ordered and unordered lists (`ol`, `ul`, `li`) | preserve | `<list type="ordered|bulleted"><item>` | Keep container and item boundaries; nested lists remain nested. |
| Verse, song, and poem blockquotes | preserve | `<quote><lg><l>` | `z3998:verse`, `z3998:song`, and `z3998:poem` all carry line structure; note-body instances are included after note resolution. |
| Quoted inline text and citations (`q`, `cite`) | preserve | `<q>` and `<bibl>`/`<title>` | The wrapper is normalized, but visible text and citation boundaries survive. |
| Note-body block structure | preserve | nested `<p>`, `<quote>`, and inline TEI elements inside `<note>` | Do not collapse endnote paragraphs or verse into a single note string. |

**Verified 2026-07-15:** TEI validation, census gates, clean-text projection, and loss ledgers pass
for *The Pilgrim's Progress* and *The Imitation of Christ*. Viewer smoke should inspect each work's
front matter, a chapter argument, an endnote, and a verse/list carrier.

## Class: Project Gutenberg marked-up plain text (Calvin *Institutes*, volumes 1-2)

| Feature (census name) | Ruling | TEI carrier | Notes |
|---|---|---|---|
| Work scope and Gutenberg wrapper | preserve / excluded | `<front>`, `<body>`, `<back>` | Preserve the selected work; exclude Project Gutenberg license wrapper text and the Vol. II index after the explicit work boundary. |
| Books and chapters (`books`, `chapters`) | preserve | nested `<div type="book|chapter" n xml:id>` | Book III is assembled from both volumes into one logical book; IDs remain source-derived. |
| Front matter (`front_matter`) | preserve | `<front><div type="titlepage">` | The two volume title/translator blocks are content of the rendering and remain available for provenance/display. |
| Underscore emphasis (`emphasis`) | preserve | `<hi rend="italic">` | Only true underscore-delimited emphasis is mapped; literal snake_case text remains literal. |
| Numeric note anchors (`note_anchors`) | preserve | `<ref type="note" target="#slug-note-N">` | Vol. I's 2,016 sequential `(N)` refs and Vol. II's 1,489 `[N]` refs resolve to source-derived note IDs. |
| Per-volume footnote blocks (`note_bodies`) | preserve | one `<back>` with per-volume `<div type="notes"><note place="end">` containers | Vol. I contributes 2,016 bodies and all are referenced; Vol. II contributes 1,490 bodies, of which 1,489 have inline refs and one is unreferenced. This remains a per-volume apparatus. |
| Projection losses | explicit | `*.loss.json` | HF clean text intentionally drops notes and markup; the receipt accounts for dropped/normalized nodes, subject to the integrity warning above. |

**Verified 2026-07-16:** the Calvin TEI artifact validates, the census gate matches books/chapters,
1,361 body paragraphs, front matter, emphasis, 3,505 resolving refs, and 3,506 notes, and its
projection ledger passes. Vol. I pairing consumes only the next expected note number in source
order; non-anchor parenthetical numbers are left literal or excluded with the Gutenberg wrapper.

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

**Verified 2026-07-16:** TEI validation and strict-v2 projection ledgers pass for
`book-of-common-prayer.bcp-1549`, `bcp-1559`, `bcp-1662`, and `bcp-1928-collects`. Viewer smokes now
cover all four renderings; the 1559 and 1928 captures use distinctive body text and pass the
viewer's rendered-DOM checks (upgraded TEI elements, nonzero paragraphs, and no dangling note
references). B04-B06 also deliver speaker roles, body-peer 1662 collects, and rendering-specific
metadata without an unsupported translator.

### BCP 1559 legacy-to-current record reconciliation

The old JSON contains 14 sections. The current TEI contains 16 source-page service carriers, and
the clean projection intentionally emits one row per carrier, including empty carriers: 16 rows.
The complete mapping is below; legacy numbers are one-based positions in
`data/structured-text/bcp-1559.json`.

| Source page / current service | Legacy section | Current state |
|---|---:|---|
| `Baptism_1559.htm` — Baptism | 1 | shared |
| `BCP_1559.htm` — The 1559 Book of Common Prayer | — | current-only; empty service |
| `Burial_1559.htm` — Burial | 2 | shared |
| `Churching_of_Women_1559.htm` — Churching of Women & Commination | 3 | shared combined page; it already contains both rites |
| `Commination_1559.htm` — A Commination against Sinners… | — | current-only duplicate source page; empty service, so it is not a second delivery of the combined page's text |
| `Communion_1559.htm` — Holy Communion | 4 | shared |
| `Confirmation_1559.htm` — Catechism & Confirmation | 5 | shared |
| `EP_1559.htm` — Evening Prayer | 6 | shared |
| `front_matter_1559.htm` — Act of Uniformity; Preface; and Of Ceremonies | — | current-only; empty service |
| `Godly_Prayers.htm` — Godly Prayers | 7 | shared |
| `JamesI_Procl_Uniformity.htm` — James I's Proclamation of Uniformity | 8 | shared |
| `Kalendar_1559.htm` — Kalendar & Tables | 9 | shared identity; empty current service |
| `Litany_1559.htm` — Litany | 10 | shared |
| `Marriage_1559.htm` — Marriage | 12 | shared |
| `MP_1559.htm` — Morning Prayer | 11 | shared |
| `Visitation_Sick_1559.htm` — Visitation of the Sick | 14 | shared |
| `PDF1623.htm` — mis-titled “Churching of Women & Commination” | 13 | legacy-only source-site download notice: 4 blocks / 173 words about a 1623 PDF, correctly excluded from the 1559 TEI |

Thus the arithmetic is `14 legacy - 1 legacy-only PDF notice + 3 current-only source-page
carriers = 16 current rows`. Thirteen legacy sections map one-to-one to current services. The
Churching page remains the same combined Churching-and-Commination unit on both surfaces; there is
no additional unaccounted merge or split. The four empty services are exactly **The 1559 Book of
Common Prayer**, **A Commination against Sinners, from the 1559 Book of Common Prayer**, **Act of
Uniformity; Preface; and Of Ceremonies**, and **Kalendar & Tables**.

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

**Verified 2026-07-07:** TEI validation and projection ledgers passed for Athanasius, *On the
Incarnation*, and Owen, *Of the Mortification of Sin*. Viewer smoke loaded the Owen TEI through
`viewer/index.html`.

## Class: Internet Archive DjVuTXT (Fisher *Marrow of Modern Divinity* proof witness)

| Feature | Ruling | TEI carrier | Notes |
|---|---|---|---|
| Parts, chapters, commandments, sections | preserve | nested `<div type>` | Raw OCR forms remain verbatim; absent commandment headings are not fabricated. |
| Dialogue | preserve where high-confidence | `<sp><speaker>` | 455 high-confidence starts are carried; 123 ambiguous starts remain prose rather than guessed. |
| OCR errors and inline marks | preserve | text | The converter does not silently repair OCR or invent note boundaries. |
| Running headers and page-number lines | excluded | — | OCR wrapper noise, not work content. |

**Verified 2026-07-16:** the bounded Fisher TEI validates and its census agrees on 2 parts, 4
chapters, 8 commandments, 41 structural sections, 6 synopsis lines, and 455 dialogue carriers. Its
ledger passes subject to the integrity warning above. This does not migrate general IA OCR.

## Class: Spurgeon MTP sermon HTML (proof works 1, 15, and 317)

| Feature | Ruling | TEI carrier | Notes |
|---|---|---|---|
| Sermon article scope | preserve | `<div type="sermon">` | Converter scopes to the article and excludes the five-item site navigation on every page. |
| Ordered lists and items | preserve | `<list type="ordered"><item>` | The proof set carries 5 lists, 5 items, and 1 nested list. |
| Paragraphs, quotations, line breaks, scripture refs | preserve | `<p>`, `<quote>`, `<lb>`, `<ref>` | Proof census and TEI carrier counts agree. |

**Verified 2026-07-16:** the proof artifact validates and its ledger passes subject to the integrity
warning above. **Status: proof works, 3 of 3,547**; the family-wide JSON still flattens list
container and ordinal semantics.

## Projection defaults (all classes)

The HF training projection targets clean faithful text (maintainer decision, 2026-07-02 NSH
alignment): structure headings and `<argument>` survive as text; notes, page breaks, `<ref>`
annotations, emphasis markup, and front/back matter are intentionally dropped and should be
accounted for per node ID. Until the P1 checker fix lands, a ledger PASS confirms accounting but not
complete text delivery. Other projections rule per output; the same caveat applies.
