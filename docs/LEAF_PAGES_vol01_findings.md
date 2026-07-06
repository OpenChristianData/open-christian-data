# Leaf-Page Identification — NSH vol_01

**Investigation date:** 2026-06-05  
**Source:** OCR text extracted from `reports/s1-sidecars/tesseract-py314-v1/vol_01/pages/leaf_*.json`  
**Method:** SHA-256 comparison to identify 6 duplicate leaf_ images (byte-identical to `page_0001`), then OCR text review of all 46 unique leaf_ sidecars.

## Duplicate leaf_ pages (byte-identical to page_0001 — blank placeholder)

These 6 files are not unique scans; they duplicate the blank `page_0001` image and carry no content:

`leaf_0001`, `leaf_0003`, `leaf_0004`, `leaf_0535`, `leaf_0538`, `leaf_0540`

---

## Unique leaf_ pages: identification table

| Stem | What it is | Recommendation |
|---|---|---|
| `leaf_0000` | Google Books digitization notice ("This is a digital copy of a book…") | **Drop** — digitizer addition, not part of the original work |
| `leaf_0002` | Blank page | **Drop** — no content |
| `leaf_0005` | Blank page — ink transfer artifact from pressing against adjacent page; no text | **Drop** — no content |
| `leaf_0006` | Blank page | **Drop** — no content |
| `leaf_0007` | Blank page | **Drop** — no content |
| `leaf_0008` | Blank page | **Drop** — no content |
| `leaf_0009` | **Title page** — full title, subtitle ("Embracing Biblical, Historical, Doctrinal, and Practical Theology…"), series description, editor-in-chief Samuel Macauley Jackson, Funk & Wagnalls | **Front matter** |
| `leaf_0010` | **Copyright page** — "Copyright, 1908, by Funk & Wagnalls Company; Registered at Stationers' Hall, London; Published May, 1908" | **Front matter** |
| `leaf_0011` | **Editorial staff list** (partial) — Charles Colebrook Sherman, George William Gilmore, Clarence Augustine Beckwith, Henry King Carroll and others | **Front matter** |
| `leaf_0012` | **Editorial staff list continued** — Bousset, Brieger, Briggs, von Buchrucker, Buhl and others | **Front matter** |
| `leaf_0013` | **Editorial staff list continued** — Hoelscher, Hofmann, Jeremias, Kattenbusch and others | **Front matter** |
| `leaf_0014` | **Editorial staff list continued** — Pick, Price, Radlach, Rietschel, Rogge and others | **Front matter** |
| `leaf_0015` | **Preface p. [ix]** — opening paragraphs; origins in Hauck's Realencyklopädie and Herzog's encyclopedia (page inferred from sequence; no running header on section-opening pages) | **Front matter** |
| `leaf_0016` | **Preface p. x** — Civil War interruption of first American edition; Philip Schaff's involvement (1877) | **Front matter** |
| `leaf_0017` | **Preface p. xi** — methodology for collecting biographical data; blank-questionnaire process | **Front matter** |
| `leaf_0018` | **Preface p. xii** — bibliography methodology; Gilmore as bibliography editor; Bernhard Pick as translator | **Front matter** |
| `leaf_0019` | **Preface p. xiii** — German bibliography sources; Hinrichs' Bücher-Katalog, Fünfjähriger Bücher-Katalog | **Front matter** |
| `leaf_0020` | **Preface p. xiv** — English bibliography sources; Darling's Cyclopedia Bibliographica (London, 1854) | **Front matter** |
| `leaf_0021` | **Preface p. xv** — Roman Catholic sources; Kirchenlexikon of Wetzer and Welte (Freiburg, 1880–1903) | **Front matter** |
| `leaf_0022` | **Preface p. xvi** — "Rainbow Bible" / Polychrome Bible; composite-document criticism | **Front matter** |
| `leaf_0023` | **Preface p. xvii** — Palestine geography bibliography; Röhricht, Tobler topography | **Front matter** |
| `leaf_0024` | **Preface p. xviii** — Patristic source collections; Martène, Gallandi Bibliotheca veterum patrum | **Front matter** |
| `leaf_0025` | **Preface p. xix** — Corpus scriptorum historiae Byzantinae (Bonn, 1828–78); Italian medieval sources | **Front matter** |
| `leaf_0026` | **Preface p. xx** — Rolls Series (Rerum Britannicarum, London, 1858–91); Hardy's Descriptive Catalogue | **Front matter** |
| `leaf_0027` | **Preface p. xxi** — General Church History; Schürer, Neander, standard survey works | **Front matter** |
| `leaf_0028` | **Preface p. xxii** — Janssen's History of German People; French Church history bibliography (Molinier) | **Front matter** |
| `leaf_0029` | **Preface p. xxiii** — Papal history bibliography; Creighton, Ranke, Nielsen | **Front matter** |
| `leaf_0030` | **Preface p. xxiv** — Monastic orders bibliography; Cistercians, Franciscans (Wadding) | **Front matter** |
| `leaf_0031` | **Recent bibliography supplement** — post-1907 works listed alphabetically: Abbott, Abrahams and others | **Front matter** |
| `leaf_0032` | **Recent bibliography supplement continued** — Apocrypha (Jesus Sirach), Apollonius of Tyana | **Front matter** |
| `leaf_0033` | **Abbreviations key** (table) — ADB, AJP, Creighton Papacy, and others with full citations | **Front matter** |
| `leaf_0034` | **Abbreviations key continued** — Haddan & Stubbs Councils; Harnack History of Dogma | **Front matter** |
| `leaf_0035` | **Abbreviations key p. xxix** — Pastor, PEF, PEQ, Pliny, Psalms abbreviations | **Front matter** |
| `leaf_0036` | **Transliteration key** — Hebrew/Aramaic and Greek character equivalents; vowel pronunciation guide | **Front matter** |
| `leaf_0037` | **Body article: AACHEN, SYNODS OF** — opens the encyclopedia body; Charlemagne; Admonitio generalis | **Include in body corpus** |
| `leaf_0038` | **Body articles: Aaron / Abbey** — Aaron and the golden calf; Abbey article continuation | **Include in body corpus** |
| `leaf_0039` | **Body article continuation** — bibliographic tail of a French Reformed theologian article (Rotterdam 1684, London 1694 translations); L'Art de se connaître soi-même; Malebranche | **Include in body corpus** |
| `leaf_0040` | **Body articles: Abbey continued** — German Klöster bibliography (Hasse, Koch, Hauntinger, Sutter); Capuchin monasteries | **Include in body corpus** |
| `leaf_0041` | **Body articles: Abbo / Abbot** — textual critic; NT Revision Company (1871); Society of Biblical Literature (1880) | **Include in body corpus** |
| `leaf_0042` | **Body articles: Abbot, Robert / Abdias** — Bishop of Salisbury; Balliol College; regius professor | **Include in body corpus** |
| `leaf_0043` | **Body article: Abbott, Jacob** — Young Christian series, Rollo Books, Franconia Stories biography | **Include in body corpus** |
| `leaf_0044` | **Body article: Abdias** — bibliographic entry with Latin source citations and NSH cross-references | **Include in body corpus** |
| `leaf_0045` | **Body articles: Abeel / Abelard** — Abelard at the Paraclete; Heloise; John of Salisbury at lectures (1136) | **Include in body corpus** |
| `leaf_0536` | Blank page (end matter) | **Drop** — no content |
| `leaf_0537` | Blank page (end matter) | **Drop** — no content |
| `leaf_0539` | Library circulation stamp: "DOES NOT CIRCULATE"; garbled surrounding OCR | **Drop** — library marking, not source content |

---

## Summary counts

| Class | Count | Stems |
|---|---|---|
| Drop (blanks) | 7 | leaf_0002, leaf_0005, leaf_0006, leaf_0007, leaf_0008, leaf_0536, leaf_0537 (all blank — leaf_0005 is ink transfer artifact) |
| Drop (non-original) | 2 | leaf_0000 (Google notice), leaf_0539 (library stamp) |
| Front matter | 27 | leaf_0009–leaf_0036 |
| Body corpus | 9 | leaf_0037–leaf_0045 |
| **Total unique** | **46** | |

Duplicate leaf_ pages (drop — byte-identical to blank `page_0001`): `leaf_0001`, `leaf_0003`, `leaf_0004`, `leaf_0535`, `leaf_0538`, `leaf_0540`

---

## Recommendation

The 46 unique `leaf_` pages split into four clean classes and the recommendation differs for each. The 9 non-content pages (7 blanks, the Google Books notice, and the library circulation stamp) should be dropped entirely — they carry no encyclopedic content and two of them are digitizer artifacts rather than original book content. The single unreadable scan (`leaf_0005`) is almost certainly a frontispiece or plate; its OCR is noise, and it should be dropped from the text corpus, though a note that an illustration exists at that physical position in the book may be worth preserving in metadata. The 27 front-matter pages (`leaf_0009`–`leaf_0036`) represent a coherent and substantial block of original 1908 content: title page, copyright, four pages of editorial staff, a 16-page bibliographic preface (pp. ix–xxiv) that constitutes original scholarship in its own right, a recent-works supplement, three pages of abbreviation tables, and a transliteration key. These should be included in the published corpus as a named front-matter section, not discarded. The 9 body-article pages (`leaf_0037`–`leaf_0045`), covering entries from AACHEN through ABELARD, are the most consequential finding: they are genuine encyclopedia body text with no `page_` counterpart, meaning the `page_` sequence as currently ingested silently omits the first several entries in the A section. These 9 pages must be included in the body corpus to avoid a gap at the very start of the alphabetic run. The `page_sequence` field derived from leaf filenames will report sequence 1 for both `leaf_0000` and `leaf_0001` due to the digit-parsing convention; for publication purposes these pages should be ordered by filename digit and positioned before `page_0001` in any merged sequence.
