# Hugging Face v0.2.0 source attribution audit

**Date:** 2026-07-17
**Scope:** The 12 JSONL files in `exports/huggingface/`, their source configs,
source-specific documentation, and the current GitHub and Hugging Face README
drafts. This is an evidence and publication audit, not legal advice.

## Executive finding

Source attribution has been done **partly**, not completely. The GitHub README
has a substantial Sources section, but the Hugging Face card only names a few
archives in passing. Several GitHub source mappings are stale, and neither page
currently gives Hymnary.org or CCEL the requested visible credit.

The release should have:

1. a short, visible **Sources and acknowledgments** section in the Hugging Face
   card;
2. the same principal-source list in the GitHub README;
3. a comprehensive release source ledger, generated from the actual release's
   `_source_url` and `_source_id` fields; and
4. per-record provenance retained as the authoritative route back to a specific
   edition or digitization.

Before publication, four rights issues need resolution or source-level review
rather than acknowledgment alone:

- five modern ESV passages are currently marked `cc0-1.0`; and
- the JWBickel/BibleDictionaries parser says permission for the upstream
  structured JSONL is still pending;
- the four Didache prayers need confirmation against an independently
  public-domain transcription; and
- the HistoricalChristianFaith source warns that a small number of quotations
  may use modern copyrighted translations.

Credit does not convert copyrighted or unlicensed data into CC0.

## What “source” means here

Three distinct layers must not be collapsed into one license claim:

1. **The underlying work or translation.** Most represented books and historic
   translations are public domain; the Berean Standard Bible is separately
   dedicated to CC0.
2. **The edition, transcription, digitization, or database.** CCEL, Internet
   Archive, Standard Ebooks, Hymnary.org, HelloAO, CrossWire, and the other
   providers did real work to make the text available. That layer can have its
   own terms even when the old book is public domain.
3. **Open Christian Data's schema, processing, and release packaging.** The
   published dataset is intended to be CC0, while repository code, schemas, and
   tooling are separately CC BY-NC 4.0 (`docs/LICENSING.md:3-22`,
   `README.md:289-294`).

The public wording should therefore say that the collection brings together
public-domain and CC0 texts **through** named digitization and data projects. It
should not imply that an archive owns the underlying historic work, or that an
underlying public-domain work makes every modern transcription automatically
CC0.

## Principal sources represented in the 12 release files

Counts below were grouped from `_source_url` in the actual JSONL files under
`exports/huggingface/`. They are release records, not books or words. Counts are
included here to prove representation and should not be the center of the
public acknowledgment.

| Source project or organization | Material represented in v0.2.0 | Release evidence and repo evidence | Credit or rights posture |
|---|---|---|---|
| [Christian Classics Ethereal Library (CCEL)](https://www.ccel.org/) | 163,369 long-form passages; 768 commentary entries; 732 devotional entries; 335 doctrinal-document passages; 14 prayers; 202 sermons; 8,351 Schaff-Herzog entries jointly sourced with Internet Archive | `exports/huggingface/structured_text.jsonl`, `commentary.jsonl`, `devotional.jsonl`, `doctrinal_document.jsonl`, `prayer.jsonl`, `sermon.jsonl`, `reference_entry.jsonl`; examples at `sources/commentaries/expositors-bible/config.json:27-42` and `sources/devotionals/spurgeons-morning-evening/config.json:16-20` | Local permission confirms parsing ThML for underlying PD text and asks for “sourced via CCEL.org”; see `docs/sources/ccel-permission.md:3-17`. Attribution is appreciated, not described there as a legal condition. |
| [Internet Archive](https://archive.org/) | 62,726 long-form passages; 851 catechism entries; 493 commentary entries; 172 doctrinal passages; 2,512 direct reference entries plus part of the 8,351 Schaff-Herzog entries; 257 sermons | Actual export URLs; representative edition evidence at `sources/reference/hastings-dictionary-of-the-bible/config.json:45-52` | No collection-wide attribution condition is documented in this repo. Credit Internet Archive as a major digitization and access provider; retain the item URL per record. Google Books and British Library should be retained in edition provenance when their scans underlie IA OCR. |
| [Project Gutenberg](https://www.gutenberg.org/) | 23,292 long-form passages; 2,070 catechism entries; 96 commentary entries; 1,255 sermons | Actual export URLs and source configs under `sources/structured-text/`, `sources/catechisms/`, `sources/commentaries/`, and `sources/sermons/` | The release strips Gutenberg boilerplate and republishes underlying PD text. No additional mandatory credit is documented locally, but Gutenberg is a principal source and should be acknowledged. |
| [Standard Ebooks](https://standardebooks.org/) | 4,863 passages from eight books and 36 MacDonald sermons | `sources/standard-ebooks/*/config.json`; each local upstream `LICENSE.md` says the source text is believed US-PD and Standard Ebooks contributors dedicate their contributions under CC0, e.g. `raw/standard_ebooks/john-bunyan_the-pilgrims-progress/LICENSE.md:1` | No attribution requirement under CC0. Credit is appropriate because its editorial and encoding work is directly used. |
| [CrossWire SWORD](https://www.crosswire.org/sword/) | 39,390 commentary entries (Barnes, Calvin, Wesley); 732 Daily Light entries; 5,322 Nave entries | `sources/commentaries/barnes/config.json:16-24`; `sources/devotionals/daily-light/config.json:21-27`; actual export URLs | The selected modules are recorded as public domain. Credit CrossWire as the module distributor and retain module-specific provenance. Module licenses must continue to be checked individually; “SWORD” is a format/ecosystem, not a blanket content license. |
| [HelloAO Bible API](https://bible.helloao.org/) | 74,322 commentary entries from Adam Clarke, Jamieson-Fausset-Brown, John Gill, Keil-Delitzsch, and Matthew Henry | `sources/commentaries/adam-clarke/config.json:13-17` and sibling configs; actual export URLs | HelloAO labels these texts with the Public Domain Mark. PDM is a rights-status mark, not a license with an attribution requirement. Credit HelloAO as the API and digitized-data provider. |
| [Hymnary.org at Calvin University](https://hymnary.org/) | 34,904 public-domain hymn texts | `sources/hymns/hymnary-pd/config.json:2-15`; `data/hymns/hymnary-pd/README.md:1-15` | Explicit human request: link to Hymnary.org and encourage application developers to submit their projects through [Hymnary's contact page](https://hymnary.org/contact). The repo presents this as requested credit, not a legal license condition. |
| [HistoricalChristianFaith Commentaries-Database](https://github.com/HistoricalChristianFaith/Commentaries-Database) | All 70,164 Church Fathers quotation records | `exports/huggingface/church_fathers.jsonl`; `raw/Commentaries-Database/LICENSE:1-10` | The database compilation is released into the public domain without an attribution requirement. Its own license warns that a small number of quotations may come from copyrighted translations. Credit the compilation, and do not repeat an unqualified “all text is unambiguously public domain” claim. |
| [Scrollmapper `bible_databases`](https://github.com/scrollmapper/bible_databases) | Eight Bible editions and 251,309 verse records: ASV, Darby, Douay-Rheims Challoner, JPS 1917, KJV, KJVA, Webster, and YLT | `sources/bible-text/asv/config.json:9-16` and sibling configs; `THIRD_PARTY_NOTICES.md:7-37` | The underlying editions are recorded as PD. Scrollmapper's repository is MIT; its notice must accompany copies or substantial portions of the licensed software (`raw/bible_databases/LICENSE:1-20`). Retain `THIRD_PARTY_NOTICES.md`. Do not describe the Bible text itself as MIT. |
| [Berean Bible](https://berean.bible/) | Berean Standard Bible, 31,086 verse records | `sources/bible-text/bsb/config.json:2-14`; `raw/bsb/LICENSE.md:1-37` | BSB is CC0. No attribution is legally required, but visible credit avoids obscuring the modern translation project. The stale `source_repository` at `sources/bible-text/bsb/config.json:13` should be corrected. |
| [The Kingdom Collective](https://thekingdomcollective.com/spurgeon/) | 3,547 Metropolitan Tabernacle Pulpit sermons | `sources/sermons/spurgeon-mtp/config.json:25-33`; `exports/huggingface/sermon.jsonl` | The sermons are PD. The config records the site's digitization lineage and says no terms of service were found. Credit The Kingdom Collective, including Emmett O'Donnell and Benry Yip if room permits, as the digitization route. |
| [JWBickel/BibleDictionaries](https://huggingface.co/datasets/JWBickel/BibleDictionaries) | 11,145 dictionary entries plus 623 Torrey topical entries | `build/parsers/bible_dictionaries.py:371-450`; `exports/huggingface/reference_entry.jsonl`; `exports/huggingface/topical_reference.jsonl` | **Unresolved:** the parser explicitly says “license confirmation pending (EMAIL-4 sent)” for JWBickel's structured JSONL (`build/parsers/bible_dictionaries.py:381-386`). The historical dictionary text being PD does not settle rights in the modern structured dataset. Resolve or replace before publishing as CC0. |
| [New Advent](https://www.newadvent.org/cathen/) | 3,674 Catholic Encyclopedia entries | `sources/reference/catholic-encyclopedia/config.json:2-13`; `exports/huggingface/reference_entry.jsonl` | The 1907 work is marked PD, and the parser preserves per-article contributor credit. No explicit permission or terms analysis for the New Advent transcription is recorded. Credit New Advent and retain the article/contributor provenance; consider documenting the digitization-rights basis. |
| [Wikisource contributors](https://en.wikisource.org/wiki/Didache_%28Lake_translation%29) | Four prayers from the Didache, Kirsopp Lake translation | `sources/prayers/didache/config.json:10-19`; `exports/huggingface/prayer.jsonl` | The Lake translation page identifies the work as public domain. The config says OCD downloaded Wikisource wikitext through its API. Wikisource's general policy licenses user contributions under CC BY-SA 4.0/GFDL. Confirm that the copied text is solely the PD edition or independently collate it against a PD scan; otherwise share-alike/attribution obligations may attach. |

## Smaller directly represented source sites

The sources above are the principal projects to name in a concise public
acknowledgment. A comprehensive generated ledger should additionally preserve
these directly represented providers and hosts:

- British Library: one catechism source (114 entries) and a scan underlying
  Hastings volume 5;
- Reformed Reader (118 catechism entries);
- Blue Letter Bible (82 catechism entries);
- apostles-creed.org (129 catechism and 420 doctrinal-document records);
- The Westminster Standard (71 doctrinal-document records);
- University of Michigan EEBO (32 doctrinal-document records);
- Christian History Institute (69 doctrinal-document records);
- `reformed-standards/compendium` (159 doctrinal-document records);
- Southern Baptist Theological Seminary (20 doctrinal-document records);
- CRCNA, Anabaptists.org, OnTheWing, and Wikiwand (small doctrinal sources);
- EpiscopalNet (102 prayers);
- Lynda M. Howell's BCP 1662 site at eskimo.com (85 prayers and 88 long-form
  passages);
- Justus Anglican (3,945 Book of Common Prayer passages); and
- Covenanter.org (879 long-form passages).

Five Literal Word pages also occur in the export, but they point to ESV text and
are a rights blocker, not an acknowledgment candidate. See below.

## Mandatory, requested, and voluntary credit

### Confirmed legal notice

- **Scrollmapper MIT notice.** The copyright and permission notice must be
  retained with copies or substantial portions of the MIT-licensed repository
  material (`raw/bible_databases/LICENSE:1-20`). The current full notice in
  `THIRD_PARTY_NOTICES.md:7-37` should remain available from both publication
  surfaces. It applies to Scrollmapper's licensed repository material, not to
  the underlying public-domain or CC0 Bible text.

### Explicitly requested or appreciated

- **Hymnary.org:** “Public-domain hymn texts provided by
  [Hymnary.org](https://hymnary.org/) at Calvin University. If you build with
  the hymn collection, please link to Hymnary.org and tell them about your work
  through [their contact page](https://hymnary.org/contact).” This implements
  `data/hymns/hymnary-pd/README.md:6-15`.
- **CCEL:** use the agreed phrase **“sourced via
  [CCEL.org](https://www.ccel.org/)”**. Local correspondence records that this
  is appreciated, not legally required (`docs/sources/ccel-permission.md:3-17`).

### Voluntary but important acknowledgments

Credit all principal projects in the table. Open licensing removes a legal
attribution requirement in several cases; it does not make the upstream labor
invisible. In particular, name Standard Ebooks, HistoricalChristianFaith,
HelloAO, CrossWire, Project Gutenberg, Internet Archive, Berean Bible, The
Kingdom Collective, New Advent, and JWBickel once their rights status is
resolved.

## Rights blockers and cautions

### 1. Five ESV records are mislabeled CC0

The release contains five doctrinal-document records sourced from
`esv.literalword.com` and labels each `_license` as `cc0-1.0`:

- `christ-hymn-of-colossians` — Colossians 1:15-19;
- `christ-hymn-of-philippians` — Philippians 2:6-10;
- `christian-shema` — 1 Corinthians 8:6;
- `confession-of-peter` — Matthew 16:16; and
- `shema-yisrael` — Deuteronomy 6:4-5.

The source files show both the modern source URL and CC0 label, and in the two
longer cases contain substantial verbatim passages (`data/doctrinal-documents/christ-hymn-of-colossians.json:15-40`,
`data/doctrinal-documents/christ-hymn-of-philippians.json:15-40`; the remaining
three are evidenced at `data/doctrinal-documents/christian-shema.json:14-39`,
`data/doctrinal-documents/confession-of-peter.json:15-40`, and
`data/doctrinal-documents/shema-yisrael.json:14-39`). The upstream Creeds.json
README itself lists these Crossway-derived entries as copyrighted and says the
repository as a whole is not licensed for reuse (`raw/Creeds.json/README.md:11-23`).

**Required action:** remove the five records, replace the wording with a verified
public-domain/CC0 translation and regenerate, or obtain an appropriate license.
Attribution alone is not a fix.

### 2. JWBickel structured-data rights are unresolved

The parser's own provenance note says the underlying nineteenth-century texts
are public domain but the structured JSONL license confirmation is still
pending (`build/parsers/bible_dictionaries.py:381-386`). The live upstream
dataset card currently exposes no clear license metadata.

**Required action:** obtain and record permission/license, or rebuild the three
dictionaries and Torrey from independently licensed/public-domain editions
before including them in a CC0 release.

### 3. Wikisource transcription layer needs a clean basis

The 1912 Lake translation is PD, but the source config says the data came from
Wikisource API wikitext (`sources/prayers/didache/config.json:14-18`). Wikisource
generally licenses editor contributions under CC BY-SA 4.0 and GFDL, while the
work page marks the historic translation itself PD.

**Required action:** document that the exported four passages are a faithful
copy of the PD edition with no copyrightable Wikisource additions, or collate
them against an independent PD scan. If editor-created material was copied,
CC0 is not the correct release posture.

### 4. HistoricalChristianFaith has an explicit translation warning

Its public-domain dedication says most quotations are from PD translations but
that a small number may originate in copyrighted translations
(`raw/Commentaries-Database/LICENSE:1-10`). This does not prove that a specific
OCD record is infringing, but it directly contradicts a blanket claim of total
certainty.

**Required action:** retain source-level and quote-level provenance, continue
the correction/removal route, and use careful public wording rather than
“unambiguously public domain.”

### 5. CCEL permission is narrower than a blanket public-domain claim

Local correspondence says CCEL's copyright applies to files and formatting,
not the underlying PD texts; it permits parsing, asks for credit, and says not
to sell CCEL files or derivatives of their formatting
(`docs/sources/ccel-permission.md:3-17`). CCEL's current official copyright
policy also distinguishes PD books from copyrighted introductions, cover art,
special contents, and a few permission-only books:
[CCEL Copyright Policy](https://www.ccel.org/about/copyright.html).

**Required action:** keep extracting the underlying PD text, avoid redistributing
CCEL markup/formatting as such, verify each edition's rights metadata, and give
the agreed credit.

## Stale or inaccurate public claims

Do not carry these claims into the rewritten card:

1. `README.md:255` links `thiagobodruk/bible`, but the eight represented PD Bible
   editions actually point to `scrollmapper/bible_databases`. The BSB config
   also has the stale repository field at `sources/bible-text/bsb/config.json:13`.
2. `README.md:256` attributes Expositor's Bible and Treasury of David to
   HelloAO. The release points to CCEL and Internet Archive respectively.
3. `README.md:261` misattributes several sermon sources. The release shows
   Maclaren via Gutenberg, Luther and Newman via Internet Archive, Wesley via
   CCEL, and MacDonald via Standard Ebooks.
4. `README.md:264` says Andrewes' *Private Devotions* came through Gutenberg;
   the release points to CCEL.
5. `README.md:265` says Schaff-Herzog came through Gutenberg; the release points
   to CCEL and Internet Archive.
6. `README.md:266` says all authors died before 1928 and all texts are
   unambiguously public domain. That is not a sufficient rights test, does not
   describe the modern CC0 BSB project, conflicts with the
   HistoricalChristianFaith translation warning, and is false as a blanket
   statement while the five ESV records remain.
7. `docs/HUGGINGFACE_DATASET_CARD.md:149-162` names only four source families and
   does not contain either requested acknowledgment.
8. `docs/LICENSING.md:5-7` says every record carries `source_license`,
   `source_url`, and `translation_year`; the exported records instead expose
   `_license` and `_source_url`, and not every schema has a meaningful
   `translation_year`. This should be rewritten as a schema-aware provenance
   claim.

## Recommended public wording

### Short acknowledgment for the dataset card

> **Sources and acknowledgments.** Open Christian Data brings together
> public-domain and CC0 texts made available through the Christian Classics
> Ethereal Library, Internet Archive, Project Gutenberg, Standard Ebooks,
> CrossWire SWORD, HelloAO, HistoricalChristianFaith, Scrollmapper's
> `bible_databases`, Berean Bible, The Kingdom Collective, New Advent, Wikisource,
> and other archives and source projects. The hymn collection was provided by
> Hymnary.org at Calvin University; if you use it, please link to Hymnary.org and
> tell them about your project. Many works were sourced via CCEL.org. Each record
> retains its specific source and edition information, and the complete source
> ledger and third-party notices are available in the source repository.

Do not include JWBickel in that final publication sentence until its license is
resolved. If it is resolved, add it explicitly.

### Rights explanation immediately after it

> The historic work, the modern digitization or database, and Open Christian
> Data's own packaging can have different rights. The dataset therefore records
> provenance at the record level rather than treating a source archive's name as
> the license for every text it hosts.

### Links to expose

- [Complete source ledger](../docs/SOURCES.md) — recommended generated artifact;
- [Third-party notices](../THIRD_PARTY_NOTICES.md);
- [Licensing policy](../docs/LICENSING.md);
- [Hymnary.org credit](../data/hymns/hymnary-pd/README.md); and
- [CCEL permission and attribution convention](../docs/sources/ccel-permission.md).

`docs/SOURCES.md` does not yet exist. It should be generated from the exact
release, not maintained as another hand-written list that can drift.

## Source references

Primary local evidence used in this audit:

- `exports/huggingface/*.jsonl` — exact release source IDs, URLs, and record
  representation;
- `sources/**/config.json` — edition, license, and acquisition metadata;
- `data/hymns/hymnary-pd/README.md:1-15` — Hymnary request;
- `docs/sources/ccel-permission.md:1-17` — direct CCEL permission and credit
  convention;
- `THIRD_PARTY_NOTICES.md:1-37` and `raw/bible_databases/LICENSE:1-20` —
  Scrollmapper MIT notice;
- `raw/Commentaries-Database/LICENSE:1-10` — public-domain dedication and
  translation warning;
- `raw/standard_ebooks/*/LICENSE.md` — Standard Ebooks PD/CC0 statements;
- `raw/Creeds.json/README.md:11-23` — explicit list of copyrighted records;
- `build/parsers/bible_dictionaries.py:371-450` — JWBickel pending-license note;
- `docs/LICENSING.md:1-44` — OCD licensing policy; and
- `README.md:253-266` and `docs/HUGGINGFACE_DATASET_CARD.md:147-162` — current
  public attribution surfaces.

First-party web references checked:

- [CCEL Copyright Policy](https://www.ccel.org/about/copyright.html)
- [Didache, Lake translation, at Wikisource](https://en.wikisource.org/wiki/Didache_%28Lake_translation%29)
- [Wikisource copyright and contribution policy](https://en.wikisource.org/wiki/Wikisource:Copyright_policy)
- [JWBickel/BibleDictionaries](https://huggingface.co/datasets/JWBickel/BibleDictionaries)
- [New Advent Catholic Encyclopedia](https://www.newadvent.org/cathen/)
