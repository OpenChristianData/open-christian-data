# Sources and Acknowledgments

We stand on the shoulders of all those who come before.

Open Christian Data is possible because libraries, archives, publishers,
digitization projects, software communities, and individual editors made
public-domain Christian texts available in usable forms. This page records the
principal sources represented in the planned corrected `v0.2.0` release and the credit they have
requested or deserve. Reasonable efforts have been made to verify that the texts are public domain
or separately available under CC0, subject to the unresolved questions recorded below; however, no
guarantee is made, and errors or omissions may remain.

Specific source and edition information also travels with the dataset. The
acknowledgments here do not replace record-level provenance.

## Requested acknowledgments

### Hymnary.org

The collection of 34,904 public-domain hymn texts was provided by
[Hymnary.org](https://hymnary.org/) at Calvin University for inclusion in Open
Christian Data.

If you build something with the hymn collection, please:

1. link to [Hymnary.org](https://hymnary.org/) in your application or
   publication; and
2. tell Hymnary about your project through its
   [contact page](https://hymnary.org/contact).

The source-specific credit and data notes are preserved in the
[Hymnary README](../data/hymns/hymnary-pd/README.md).

### Christian Classics Ethereal Library

Many books, sermons, commentaries, devotionals, prayers, doctrinal documents,
and reference entries were **sourced via
[CCEL.org](https://www.ccel.org/)**.

CCEL confirmed that Open Christian Data may parse its ThML files to recover
underlying public-domain text. CCEL asks to be credited for making those files
available. Its formatting and other site material are not being presented as
public domain merely because the underlying historic works are public domain.
See the [CCEL permission and attribution note](sources/ccel-permission.md).

## Principal source projects

| Source                                                                                                              | Material represented in v0.2.0                                                                 | Rights and credit notes                                                                                                                                                                   |
| ------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| [Christian Classics Ethereal Library](https://www.ccel.org/)                                                        | Books, commentaries, devotionals, sermons, prayers, doctrinal texts, and reference works       | Underlying public-domain texts recovered from CCEL files; use the acknowledgment “sourced via CCEL.org.”                                                                                  |
| [Internet Archive](https://archive.org/)                                                                            | Books, catechisms, commentaries, sermons, doctrinal documents, dictionaries, and encyclopedias | Major scan, digitization, and access provider. Item and edition URLs remain in provenance.                                                                                                |
| [Project Gutenberg](https://www.gutenberg.org/)                                                                     | Books, catechisms, commentaries, and sermons                                                   | Underlying public-domain texts are republished without Gutenberg boilerplate; Project Gutenberg remains visibly credited as the digital source.                                           |
| [Standard Ebooks](https://standardebooks.org/)                                                                      | Eight books and George MacDonald sermons                                                       | The represented editions identify the historic text as US public domain and Standard Ebooks' contributions as CC0. Its editorial and encoding work is credited.                           |
| [CrossWire Bible Society](https://www.crosswire.org/sword/)                                                         | Barnes, Calvin, and Wesley commentaries; *Daily Light*; *Nave's Topical Bible*                 | CrossWire distributes the selected public-domain SWORD modules. Each module's rights must be assessed individually.                                                                       |
| [HelloAO Bible API](https://bible.helloao.org/)                                                                     | Clarke, Jamieson-Fausset-Brown, Gill, Keil-Delitzsch, and Matthew Henry commentaries           | HelloAO marks these texts with the Public Domain Mark and is credited as the structured-data provider.                                                                                    |
| [Hymnary.org](https://hymnary.org/) at Calvin University                                                            | 34,904 public-domain hymn texts                                                                | Requested acknowledgment and project-submission invitation are reproduced above.                                                                                                          |
| [HistoricalChristianFaith Commentaries-Database](https://github.com/HistoricalChristianFaith/Commentaries-Database) | 70,164 scripture-linked Church Fathers quotations                                              | The compilation is dedicated to the public domain. Its own notice warns that a small number of quotations may derive from modern translations; see the rights follow-up below.            |
| [Scrollmapper bible_databases](https://github.com/scrollmapper/bible_databases)                                     | Eight public-domain Bible editions                                                             | The underlying Bible editions are public domain. Scrollmapper's database repository is MIT-licensed; the required notice is retained in [Third-Party Notices](../THIRD_PARTY_NOTICES.md). |
| [Berean Bible](https://berean.bible/)                                                                               | Berean Standard Bible                                                                          | The Berean Standard Bible is CC0. Visible credit is retained even though attribution is not required.                                                                                     |
| [The Kingdom Collective](https://thekingdomcollective.com/spurgeon/)                                                | *Metropolitan Tabernacle Pulpit* sermons                                                       | Credited as the digitization route for Spurgeon's public-domain sermons.                                                                                                                  |
| [JWBickel/BibleDictionaries](https://huggingface.co/datasets/JWBickel/BibleDictionaries)                            | Bible dictionaries and Torrey topical material                                                 | The historic works are public domain, but rights in the modern structured files remain unresolved; see below.                                                                             |
| [New Advent](https://www.newadvent.org/cathen/)                                                                     | *Catholic Encyclopedia* entries                                                                | The historic encyclopedia is public domain. Article contributor credit and New Advent source links are retained.                                                                          |
| [Wikisource contributors](https://en.wikisource.org/wiki/Didache_%28Lake_translation%29)                            | Four prayers from Kirsopp Lake's 1912 *Didache* translation                                    | The historic translation is public domain. The transcription-layer question is recorded below.                                                                                            |

## Other represented providers

The release also contains material sourced through or hosted by:

- the [British Library](https://www.bl.uk/);
- [Reformed Reader](https://www.reformedreader.org/);
- [Blue Letter Bible](https://www.blueletterbible.org/);
- [Apostles-Creed.org](https://www.apostles-creed.org/);
- [The Westminster Standard](https://thewestminsterstandard.org/);
- the [University of Michigan Library](https://www.lib.umich.edu/);
- [Christian History Institute](https://christianhistoryinstitute.org/);
- [Reformed Standards](https://github.com/reformed-standards/compendium);
- [The Southern Baptist Theological Seminary](https://www.sbts.edu/);
- the [Christian Reformed Church in North America](https://www.crcna.org/);
- [Anabaptists.org](https://www.anabaptists.org/);
- [EpiscopalNet](https://www.episcopalnet.org/1928bcp/);
- Lynda M. Howell's [1662 Book of Common Prayer](https://eskimo.com/~lhowell/bcp1662/);
- [Justus Anglican](http://justus.anglican.org/);
- [Covenanter.org](https://www.covenanter.org/); and
- other source sites identified in individual records.

## Rights layers

Three different things can have different rights:

1. the underlying work or translation;
2. a modern edition, transcription, digitization, or database; and
3. Open Christian Data's schema, processing, and release packaging.

An old work being public domain does not automatically make every modern
transcription or structured database CC0. Open Christian Data therefore keeps
source and edition provenance with the data and assesses source rights
separately.

The intended release posture is:

- **published dataset:** CC0 1.0 Universal;
- **underlying texts:** public domain or separately CC0; and
- **repository code, schemas, and tooling:** CC BY-NC 4.0.

## Rights follow-up from the v0.2.0 audit

The source audit found issues that require correction or additional evidence.
Attribution alone does not resolve them.

### Resolved — records removed

**Five ESV-derived doctrinal records have been removed.** The audit found five
records — `christ-hymn-of-colossians` (Col 1:15-19), `christ-hymn-of-philippians`
(Phil 2:6-10), `christian-shema` (1 Cor 8:6), `confession-of-peter` (Matt 16:16),
and `shema-yisrael` (Deut 6:4-5) — whose text was supplied by the upstream
Creeds.json project from the ESV (`esv.literalword.com`), a copyrighted modern
translation, and which were nevertheless labeled `cc0-1.0`. Each is a bare
Scripture passage rather than a composed creed, so the wording is wholly the
modern translation's and no public-domain text sits underneath to recover. They
were removed from `data/doctrinal-documents/` and from the parser's document
list; every passage remains available in the CC0 Berean Standard Bible under
`bible_text`. Restoring them as doctrinal documents requires re-sourcing the
wording from a public-domain or CC0 translation.

### Open

1. **JWBickel structured-data rights are unresolved.** The represented historic
   dictionaries are public domain, but the modern structured JSONL needs a
   recorded license or an independently built replacement.
2. **The Wikisource transcription basis needs confirmation.** The Lake
   translation is public domain, but the four exported prayers should be
   checked against an independent public-domain edition to ensure no
   contributor-created material was copied under share-alike terms.
3. **HistoricalChristianFaith carries a translation warning.** Its database
   notice says a small number of quotations may derive from copyrighted modern
   translations. Source-level review and the correction/removal route should
   remain open.

Until these are resolved, public wording should not claim that every released
record is unambiguously public domain merely because the original author died
before a particular year. Where a rights question cannot be resolved, the
affected records are removed or replaced rather than relabeled, as the five
ESV-derived records above were.

## Detailed notices and provenance

- [Licensing policy](LICENSING.md)
- [Third-party notices](../THIRD_PARTY_NOTICES.md)
- [Hymnary.org source README](../data/hymns/hymnary-pd/README.md)
- [CCEL permission and attribution](sources/ccel-permission.md)
- [v0.2.0 source attribution audit](../research/2026-07-17-huggingface-v0.2.0-source-attribution-audit.md)
