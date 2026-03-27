# Catechism Source Investigation
**Open Christian Data Project**
**Date:** 2026-03-27
**Status:** Research only — no bulk downloading performed

---

## robots.txt & ToS Summary

| Source | robots.txt finding | Bulk download verdict |
|---|---|---|
| Wikisource (wikisource.org) | Standard Wikimedia policy: 1s crawl-delay, bots must be approved for bulk harvest | Use database dumps (dumps.wikimedia.org/enwikisource) — do NOT scrape live site. Dumps are CC-BY-SA licensed and officially sanctioned. |
| CCEL (ccel.org) | 10-second crawl-delay for non-blocked agents; no paths universally disallowed | Content is free to access but bulk scraping is discouraged by crawl-delay. No official bulk download/API found. Prefer direct file links (PDF/HTML) over spidering. |
| Project Gutenberg (gutenberg.org) | robots.txt explicitly describes a robot/harvest endpoint for bulk download | Use the official robot harvest endpoint: `https://www.gutenberg.org/robot/harvest?filetypes[]=txt` — do NOT scrape main site. Mirrors preferred. Metadata available as RDF/XML. |
| bookofconcord.org | No bulk download policy found | HTML scraping with 2s+ delay acceptable for single-document fetches; do NOT mirror the full site. |
| GitHub repositories | No restrictions on git clone | `git clone` is always preferred. No rate-limiting on raw content. |
| archive.spurgeon.org | Not checked directly | Single-page fetches acceptable; not a bulk target. |

---

## 1. Decision Brief — Best Source per Catechism

| Catechism | Best Source | Format | Access Method |
|---|---|---|---|
| Westminster Shorter Catechism | **NonlinearFruit/Creeds.json** (GitHub) | JSON, numbered Q&A, proof texts as book/chapter/verse arrays | `git clone` |
| Westminster Larger Catechism | **NonlinearFruit/Creeds.json** (GitHub) | JSON, numbered Q&A, proof texts as book/chapter/verse arrays | `git clone` |
| Heidelberg Catechism | **heidelberg-catechism.com** PDF + **NonlinearFruit/Creeds.json** as cross-check | PDF (official 2011 CRC translation); JSON for machine-readable structure | wget single PDF; git clone |
| Luther's Small Catechism | **Project Gutenberg #1670** (Bente/Dau translation) | Plain text/HTML, catechism structure | robot/harvest endpoint |
| Luther's Large Catechism | **Project Gutenberg #1722** (Bente/Dau translation) | Plain text/HTML | robot/harvest endpoint |
| Keach's Catechism | **baptistcatechism.org** or **reformedreader.org** + **NonlinearFruit/Creeds.json** check | HTML (baptistcatechism.org); check Creeds.json for JSON coverage | Single-page fetch (2s delay) |
| Baptist Catechism (Spurgeon) | **archive.spurgeon.org/catechis.php** + **chapellibrary.org** PDF | HTML with Q&A and proof texts; PDF backup | Single-page fetch |
| Philaret's Catechism (Orthodox) | **CCEL** (via Schaff's Creeds of Christendom, Vol. II) + **pravoslavieto.com** HTML | HTML prose, Q&A structured but not clean numbered | Single-page fetch |
| Baltimore Catechism (Catholic) | **Project Gutenberg #14552** (No. 2) as canonical + #14551, #14553 | Plain text/HTML, numbered Q&A | robot/harvest endpoint |

**Primary recommendation:** Start with `git clone https://github.com/NonlinearFruit/Creeds.json` — it provides the Reformed catechisms in clean, structured JSON with proof texts already parsed. This covers WSC, WLC, and likely Heidelberg in a single operation. All other catechisms require individual sourcing from the sites above.

---

## 2. Per-Catechism Findings Table

### Westminster Shorter Catechism (107 Q&A, 1647)

| Field | Finding |
|---|---|
| Best source | NonlinearFruit/Creeds.json — `creeds/westminster_shorter_catechism.json` |
| Runner-up | OPC HTML at opc.org/sc.html; plain text gist at gist.github.com/lojic/4ebec7df210093bf15f1 |
| Proof texts included | Yes — OPC 1978 committee proof texts; structured as Bible reference arrays in Creeds.json |
| Proof text format | Creeds.json: `["Rom.11.36", "1Cor.10.31"]` style (book.chapter.verse notation) |
| Q&A numbering clean | Yes — fully numbered 1–107 in all major sources |
| Access method | `git clone` for Creeds.json; direct HTML for opc.org |
| License | Underlying text: public domain (1647). Creeds.json repo: **Unlicense confirmed** — 35 of 43 docs are Unlicense (direct repo inspection post-investigation) |
| Known version variants | (1) OPC 1978 proof texts — denominational standard, most scrutinised; (2) PCA 2001 proof texts — corrected version approved by GA; (3) Free Church of Scotland edition — slightly different verse citations for Q18. For OCD, prefer the OPC/PCA proof text set as it has been through committee review. |
| Special note | ReformedDevs/hubot-wsc (GitHub) also contains WSC with proof texts in CoffeeScript data files — useful cross-check but not the primary source |

### Westminster Larger Catechism (196 Q&A, 1648)

| Field | Finding |
|---|---|
| Best source | NonlinearFruit/Creeds.json — `creeds/westminster_larger_catechism.json` |
| Runner-up | Wikisource (en.wikisource.org/wiki/Westminster_Larger_Catechism) |
| Proof texts included | Yes in Creeds.json |
| Proof text format | Same array notation as WSC |
| Q&A numbering clean | Yes — numbered 1–196 |
| Access method | `git clone` |
| License | Public domain text; Creeds.json: Unlicense |
| Special note | WLC is substantially longer than WSC; proof texts are more extensive per question. Cross-check against OPC PDF (opc.org) for any variant readings. |

### Heidelberg Catechism (129 Q&A, 1563)

| Field | Finding |
|---|---|
| Best source | **heidelberg-catechism.com/pdf/lords-days/Heidelberg-Catechism.pdf** for the canonical 2011 CRC/RCA approved English text; cross-check with NonlinearFruit/Creeds.json if included |
| Runner-up | CCEL HTML at ccel.org/ccel/a/anonymous/heidelberg; Wikisource at en.wikisource.org/wiki/The_Heidelberg_Catechism (1879 RCA translation — older) |
| Proof texts included | Yes — referenced inline with alphabetical superscripts (a, b, c...) mapped to footnotes |
| Proof text format | On heidelberg-catechism.com: footnote-style, listed after each Q&A block. In CCEL: full verse text written out. |
| Q&A numbering clean | Yes — Q&A numbered 1–129 with Lord's Day groupings (LD 1–52) |
| Access method | Single PDF wget from heidelberg-catechism.com; or direct HTML fetch from CCEL |
| License | The 2011 CRC/RCA translation: copyright Faith Alive Christian Resources but widely reproduced for non-commercial use. The pre-2011 translations (pre-1923) are unambiguously public domain. For OCD, use the 1879 RCA translation via Wikisource (confirmed public domain) or the Creeds.json version if available. |
| Translation note | See Translation Notes section below |

### Luther's Small Catechism (1529)

| Field | Finding |
|---|---|
| Best source | **Project Gutenberg #1670** — "Luther's Little Instruction Book: The Small Catechism" (Bente/Dau translation, 1921, now public domain) |
| Runner-up | Wikisource (en.wikisource.org/wiki/Luther's_Small_Catechism) — same Bente/Dau translation via Concordia Triglotta; bookofconcord.org HTML |
| Proof texts included | Bente/Dau translation includes proof texts. Note: the Small Catechism's Q&A format is minimal — Luther's original is organised by topic sections (Ten Commandments, Creed, Lord's Prayer, Baptism, Communion), not a simple numbered list throughout. |
| Q&A numbering clean | Partially — structure is topic-section-based, not single sequential numbering. Questions and answers exist but are nested within sections. Requires more parser work than Westminster catechisms. |
| Access method | Project Gutenberg robot/harvest endpoint; or single HTML fetch from Gutenberg |
| License | Bente/Dau translation (1921): public domain. Concordia Publishing House copyright applies to modern LCMS translations only — do NOT use those. |
| Special note | Copyright trap: Concordia Publishing House (CPH) holds copyright on their modern translation of the Small Catechism (1986). bookofconcord.org hosts the CPH-licensed version with restrictions. Use the Bente/Dau 1921 translation from Project Gutenberg which is unambiguously public domain. |

### Luther's Large Catechism (1529)

| Field | Finding |
|---|---|
| Best source | **Project Gutenberg #1722** — "Martin Luther's Large Catechism, translated by Bente and Dau" |
| Runner-up | archive.org (several scans including Tappert translation) |
| Proof texts included | Limited — the Large Catechism is an expository treatise rather than strict Q&A. It is not structured as numbered question-answer pairs; it is organised by topic (Ten Commandments, Creed, Lord's Prayer, Baptism, Lord's Supper, Confession). Proof texts are embedded in prose. |
| Q&A numbering clean | No — the Large Catechism is not a Q&A document. It is continuous theological exposition. Parsing as Q&A pairs is not appropriate. Consider documenting it as a prose theological text, not a catechism in the Q&A sense. |
| Access method | Project Gutenberg robot/harvest endpoint |
| License | Bente/Dau translation (1921): public domain |
| Special note | Schema consideration: the Large Catechism may need a different data model from the Q&A catechisms — perhaps chapter/section/paragraph rather than question/answer/proof_texts. |

### Keach's Catechism / Baptist Catechism (1693)

| Field | Finding |
|---|---|
| Best source | **baptistcatechism.org** — dedicated site using the 1695 edition text (oldest extant copy); **reformedreader.org/ccc/keachcat.htm** has full HTML text |
| Secondary | digitalpuritan.net has plain text version; NonlinearFruit/Creeds.json may have this (check repo for `keach` or `baptist_catechism` file) |
| Proof texts included | Yes — Keach's Catechism was modelled closely on the WSC and includes scripture proofs |
| Q&A numbering clean | Yes — follows numbered Q&A format similar to WSC |
| Access method | Single-page HTML fetch from reformedreader.org or baptistcatechism.org (2s delay) |
| License | Public domain (1693/1695) |
| Historical note | Often attributed to Benjamin Keach but likely compiled by William Collins. The 1693 General Assembly of Particular Baptists commissioned it. The 1695 edition is the oldest known surviving copy. |

### Baptist Catechism — Spurgeon's Version (1855)

| Field | Finding |
|---|---|
| Best source | **archive.spurgeon.org/catechis.php** — Spurgeon Archive (Midwestern Baptist Theological Seminary), HTML with Q&A and proof texts |
| Secondary | **chapellibrary.org/pdf/books/cwpr.pdf** — PDF; blueletterbible.org/study/ccc/chs_PuritanCatechism.cfm |
| Proof texts included | Yes — cited as book/chapter:verse references after each answer |
| Q&A numbering clean | Yes — 82 questions, numbered sequentially |
| Access method | Single-page HTML fetch from archive.spurgeon.org |
| License | Public domain (1855, author d. 1892) |
| Relationship to Keach | Spurgeon edited and reprinted Keach's Catechism in 1855, shortening the expositions of the Ten Commandments and Lord's Prayer. The 82 questions differ slightly from Keach's original count. |

### Philaret's Catechism / Longer Catechism of the Orthodox Church (1823)

| Field | Finding |
|---|---|
| Best source | **CCEL** — Philip Schaff's Creeds of Christendom Vol. II (ccel.org/ccel/schaff/creeds2.vi.iii.html) includes the full Philaret catechism in English; **pravoslavieto.com/docs/eng/Orthodox_Catechism_of_Philaret.htm** has standalone HTML |
| Secondary | The 1845 Blackmore translation (Aberdeen) is the standard English version — now fully public domain |
| Proof texts included | Yes — scripture references included, but format is inline citation rather than structured proof text lists |
| Q&A numbering clean | Partially — structured as numbered Q&A throughout, but sections are grouped by theological topic (Faith, Hope, Love). Total ~617 Q&A pairs in the full version. Not a simple single-sequence numbering in all editions. |
| Access method | Single-page HTML fetch from pravoslavieto.com (standalone, easier to parse than Schaff's multi-volume work) |
| License | Blackmore 1845 translation: public domain. Schaff's Creeds of Christendom: public domain. |
| Special note | Two versions exist: the "Shorter Catechism" (simpler, for children) and the "Longer Catechism" (full version, ~617 Q&A). The OCD request is for the Longer version. |

### Baltimore Catechism (Catholic, 1885)

| Field | Finding |
|---|---|
| Best source | **Project Gutenberg #14552** — "A Catechism of Christian Doctrine, No. 2" (for confirmation classes) — this is the standard Baltimore Catechism used most widely |
| Also available | #14551 (No. 1, first communion); #14553 (No. 3, post-confirmation); #14554 (Kinkead's explanation of No. 4) |
| Proof texts included | Yes — scripture references are included |
| Q&A numbering clean | Yes — numbered Q&A format, clean sequential numbering |
| Access method | Project Gutenberg robot/harvest endpoint; or direct fetch of `https://www.gutenberg.org/ebooks/14552.txt.utf-8` |
| License | Public domain (1885, US federal government document — prepared by the Third Plenary Council of Baltimore) |
| Special note | Four numbered editions exist (No. 1–4) with increasing complexity. No. 2 is the canonical version. Kinkead's "Explanation" (No. 4) adds substantial commentary. For OCD, start with No. 2 as the clean Q&A version. |

---

## 3. Translation Notes

### Heidelberg Catechism (German original, 1563)

Three main English translation lineages exist:

1. **1879 RCA translation** — Used for over a century, now fully public domain. Available on Wikisource and CCEL. Traditional language ("thee/thy"). This is the safe public-domain choice.

2. **Traditional English (pre-2011)** — Various Reformed church editions, often based on the 1879 or related texts. Used at RCUS, PRCA, and other conservative Reformed denominations. Public domain.

3. **2011 CRC/RCA translation (Faith Alive)** — Most modern, approved by multiple Reformed synods, gender-inclusive language updates, contemporary English. Copyright Faith Alive Christian Resources. **Not free for reproduction without permission.** Avoid for OCD unless explicit permission obtained.

**Recommendation:** Use the pre-2011 translation for OCD. The 1879 RCA text on Wikisource is the cleanest unambiguous public-domain option. The RCUS traditional text (rcus.org PDF) is another public-domain option with slightly different language. Both are based on the same German third edition (Palatinate Church Order, November 1563) which is the universally accepted received text.

**Lord's Days:** All legitimate translations retain the 52 Lord's Day groupings. Any version that drops this structure has modified the original.

**Proof text notation:** The Heidelberg uses alphabetical superscripts (a, b, c) within the answer text, with verse citations listed at the end of each Q&A. This differs from the Westminster system. Schema must accommodate this inline-reference-then-footnote pattern.

### Luther's Small Catechism (German original, 1529)

1. **Bente/Dau translation (1921)** — Part of the Concordia Triglotta (German/Latin/English parallel edition). Now public domain. Available via Project Gutenberg and Wikisource. This is the scholarly standard for pre-copyright editions.

2. **Tappert translation (1959)** — From The Book of Concord, Fortress Press. More modern English. Still under copyright — do not use.

3. **CPH translations (1986+)** — Copyrighted by Concordia Publishing House. bookofconcord.org uses these. Do not use.

**Recommendation:** Bente/Dau 1921 via Project Gutenberg #1670. Note that the Small Catechism is structured as six chief parts (Ten Commandments, Apostles' Creed, Lord's Prayer, Baptism, Confession, Lord's Supper) plus appendices — not a single numbered list. The parser needs to handle nested structure.

### Luther's Large Catechism (German original, 1529)

Same translation lineage as above. Bente/Dau via Project Gutenberg #1722 is the public-domain standard. The Large Catechism is continuous theological prose — it does not have a Q&A structure at all. If OCD needs to store it, use a different schema (treatise/chapter/section) rather than question/answer.

### Philaret's Catechism (Russian/Church Slavonic original, 1823 rev. 1839)

1. **Blackmore translation (1845)** — Prepared by Rev. R. W. Blackmore, formerly chaplain to the Russia Company in Kronstadt. Published in Aberdeen. This is the standard English translation, now fully public domain.

2. Available via Schaff's Creeds of Christendom (CCEL) and standalone at pravoslavieto.com.

**Quality note:** The Blackmore translation is 19th-century formal English. No modern English critical translation of the Longer Catechism with scholarly apparatus is freely available. For OCD purposes, the Blackmore is the only realistic public-domain choice.

---

## 4. Schema Considerations

### Proof Text Format Variations

Different sources encode proof texts differently. OCD needs to normalise at ingest:

| Source type | Proof text encoding | OCD normalisation needed |
|---|---|---|
| NonlinearFruit/Creeds.json | `"proofs": [{"references": ["Rom.11.36", "1Cor.10.31"]}]` — array of arrays per proof point | Parse book.chapter.verse notation; map to standard book names |
| Westminster catechisms (OPC/PCA) | Verse ranges like "Rom. 5:12, 19; Eph. 2:1–3" — inline citation strings | Parse citation strings into structured references |
| Heidelberg Catechism | Alphabetical superscript keys (a, b, c) mapped to footnote lists per Q&A | Two-pass parse: extract superscripts from answer text, then match to footnote citation list |
| Luther's Small Catechism (Bente/Dau) | Inline citations within prose answers | Extract via regex; structure varies by section |
| Spurgeon/Keach | Inline after answer: "1 Cor. 10:31; Ps. 73:25–26" | Parse citation string format |
| Baltimore Catechism | Mixed — some inline, some footnote | Parse per section |
| Philaret | Inline citations within numbered answers | Extract via regex; Russian Orthodox book name conventions (may differ from Protestant) |

### Lord's Day groupings (Heidelberg only)

The Heidelberg Catechism has a dual structure: 129 Q&A pairs AND 52 Lord's Days. Schema should store both: `question_number` (1–129) and `lords_day` (1–52). Multiple questions share the same Lord's Day.

### Section structure (Luther's catechisms)

Luther's Small Catechism uses: `part` > `section_title` > `question` > `answer`. The Large Catechism uses: `treatise` > `chapter_title` > `paragraph`. Neither fits the simple `{question, answer, proof_texts}` model cleanly.

### Recommended minimum schema for Q&A catechisms

```json
{
  "catechism": "Westminster Shorter Catechism",
  "year": 1647,
  "tradition": "Reformed Presbyterian",
  "source": "NonlinearFruit/Creeds.json",
  "source_license": "Unlicense",
  "translation": null,
  "questions": [
    {
      "number": 1,
      "question": "What is the chief end of man?",
      "answer": "Man's chief end is to glorify God, and to enjoy him for ever.",
      "proof_texts": [
        {
          "label": "a",
          "references": ["1Cor.10.31", "Rom.11.36"]
        }
      ]
    }
  ]
}
```

For the Heidelberg, add `"lords_day": 1` to each question object. For Luther's Small Catechism, add `"part": "Ten Commandments"` and `"section": "First Commandment"`.

---

## 5. Recommended Download Sequence

### Phase 1 — Git clone (immediate, zero rate-limiting concerns)

1. `git clone https://github.com/NonlinearFruit/Creeds.json`
   - Yields: WSC, WLC in clean JSON with proof texts. Check for Heidelberg, Keach files while there.
   - License: Unlicense for public domain texts.

2. Check `meichthys/christian_foss` GitHub for any catechism datasets listed — may contain Keach's/Heidelberg references.

### Phase 2 — Project Gutenberg (official robot/harvest endpoint)

Use: `https://www.gutenberg.org/robot/harvest?filetypes[]=txt&langs[]=en`

Fetch specifically:
- **#1670** — Luther's Small Catechism (Bente/Dau)
- **#1722** — Luther's Large Catechism (Bente/Dau)
- **#14551** — Baltimore Catechism No. 1
- **#14552** — Baltimore Catechism No. 2 (canonical)
- **#14553** — Baltimore Catechism No. 3
- **#14554** — Kinkead's Explanation (No. 4)

Use 2-second delay between requests. User-Agent: `OpenChristianData/1.0 (research; open-source data project; contact: openchristiandata@gmail.com)`

### Phase 3 — Single-page HTML fetches (2s delay per domain)

For each, fetch once, store locally, parse offline. Do not spider — fetch only the known URL.

- **Heidelberg Catechism PDF**: `https://www.heidelberg-catechism.com/pdf/lords-days/Heidelberg-Catechism.pdf` — single wget, then parse PDF. (Or use CCEL HTML version which may be easier to parse.)
- **Keach's Catechism**: `https://www.reformedreader.org/ccc/keachcat.htm`
- **Spurgeon's Catechism**: `https://archive.spurgeon.org/catechis.php`
- **Philaret's Longer Catechism**: `https://www.pravoslavieto.com/docs/eng/Orthodox_Catechism_of_Philaret.htm`

### Phase 4 — Wikisource (for cross-check and any gaps)

- Do NOT scrape the live site.
- Use database dumps: `https://dumps.wikimedia.org/enwikisource/` — download the latest article dump and extract the relevant pages.
- Wikisource pages of interest: `Westminster_Shorter_Catechism`, `Westminster_Larger_Catechism`, `The_Heidelberg_Catechism`, `Luther's_Small_Catechism`.
- License: CC-BY-SA 4.0. Requires attribution.

### Phase 5 — Verification

Cross-check Creeds.json WSC proof texts against the OPC PDF (`https://opc.org/documents/SCLayout.pdf`) to confirm proof text accuracy before treating as canonical. The OPC 1978 committee proof texts are the denominational standard and the most scrutinised set available.

---

## 6. Special Research Question — WSC Digital Edition Reliability

**Which digital WSC is most reliable for proof text accuracy?**

Based on research findings:

- **The OPC 1978 committee proof texts** are the benchmark. They were prepared by a special General Assembly committee and have been reviewed over decades. The OPC publishes the authoritative PDF at opc.org/documents/SCLayout.pdf.

- **The PCA 2001 corrected proof texts** are the other denominationally approved set — reviewed and corrected by GA approval. These are substantively identical to OPC for most questions.

- **Known variant/dispute point:** Q18 — some editions cite Rom. 5:10–20 where others cite Rom. 3:10–20. The OPC/PCA editions represent the most carefully reviewed resolution of these variants.

- **NonlinearFruit/Creeds.json** draws on public-domain text sources. The WSC JSON in Creeds.json should be cross-checked against the OPC PDF before OCD treats it as authoritative. The Creeds.json project does not document which proof text set it uses.

- **Avoid:** casual web copies (apuritansmind.com, reformed.org, etc.) — these are not maintained by denominational bodies and may have transcription errors. Useful for spot checks but not for source text.

- **Academic recommendation (implicit from research):** The OPC PDF is the most authoritatively curated free digital source. Creeds.json is the most machine-readable. The ideal workflow is: use Creeds.json as the structural template, then validate proof texts against the OPC PDF.

**Clean Q&A numbering:** All major denominational sources (OPC, PCA, Free Church of Scotland) use the same 107-question numbering. There are no disputes about question boundaries or numbering — only about specific proof text citations.

---

## 7. HuggingFace Finding

No catechism datasets were found on HuggingFace in the research search. The Reformed/Protestant catechism space on HuggingFace appears to be empty as of March 2026. The Catholic Catechism of the Catholic Church (CCC) has JSON repositories on GitHub (nossbigg/catechism-ccc-json, aseemsavio/catholicism-in-json) but these are the modern CCC (post-1992), not the historical Baltimore Catechism.

**OCD opportunity:** Publishing cleaned, normalised catechism datasets to HuggingFace would fill a genuine gap in the space.

---

## 8. Key Risks and Open Questions

| Risk | Detail | Mitigation |
|---|---|---|
| Heidelberg 2011 translation copyright | Faith Alive Christian Resources holds copyright on the current ecumenical English translation | Use pre-2011 (1879 RCA) translation from Wikisource — unambiguously PD |
| CPH copyright on Luther translations | Modern LCMS/CPH translations of both catechisms are under copyright | Use Bente/Dau 1921 from Project Gutenberg only |
| Creeds.json proof text provenance | Repository does not clearly document which proof text set was used for WSC/WLC | Cross-check against OPC PDF before finalising |
| Luther's Large Catechism schema mismatch | Not a Q&A document — continuous theological prose | Needs separate schema; flag in data model before ingest |
| Philaret numbering inconsistency | Different editions number Q&A differently; some editions split the text differently | Use a single source (pravoslavieto.com) and note the edition |
| Baltimore Catechism edition selection | Four numbered editions with different audiences | Default to No. 2 as canonical; store all four with edition flags |

---

*Research conducted 2026-03-27. No bulk downloading performed. All sources identified for future download operations only.*
