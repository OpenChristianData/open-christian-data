# Upstream Data Bugs

Known issues in data received from upstream sources (HistoricalChristianFaith
Commentaries-Database, CCEL, SWORD modules, etc.). These are errors in the
source data, not OCD parser bugs. File here rather than fixing downstream so
we can report them to upstream maintainers in one batch.

Add rows as bugs are discovered during curation, parser work, or validation.
Remove rows once the upstream source has been updated and we've re-ingested.

## Format

Each row should name the upstream source, the specific file or entry, the
observed bug, and the correct value (verified against a primary source).

## Commentaries-Database (HistoricalChristianFaith)

### Verse-tag errors (wrong verse reference on TOML)

| Author | Entry ID | Observed verse tag | Correct verse (primary source) | Found |
|---|---|---|---|---|
| pope-anterus | `Eph.4.29.unknown` | Eph 4:29 | Eph 4:32 ("And be ye kind one to another") | 2026-04-15 |
| andreas-of-caesarea | `2Thess.1.8.unknown` | 2 Thess 1:8 | Rev 20:9-10 (commentary on fire-of-judgment imagery) | 2026-04-15 |
| caesarius-of-arles | `2Thess.1.8.unknown` | 2 Thess 1:8 | References Armageddon (Rev 16:16) -- likely from Exposition on the Apocalypse, not a 2 Thess commentary | 2026-04-15 |
| callistus-i-of-rome | `Rom.3.3.unknown` | Rom 3:3 | Rom 2:10 ("glory, honour, and peace, to every man that worketh good") | 2026-04-15 |

Effect: source_title on these entries is correctly set to the work the quote
actually came from, but the verse tag (and thus the entry placement in the
verse-indexed dataset) points to the wrong passage. Downstream consumers
that index by verse will mis-file these entries.

### Composite entries (two sources merged under one entry)

| Author | Entry ID | Problem | Found |
|---|---|---|---|
| cyprian | `1Pet.5.5.unknown` | Quote is a composite of Epistle XIV.3 ("Crementius the sub-deacon...") and Epistle XIX ("To the number of five, that I wrote...") -- two distinct letters spliced into one TOML block | 2026-04-15 |

Effect: no single source_title is correct. Entry left blank in OCD until
upstream splits this into two entries.

### Misattribution (content credited to the wrong person)

| Author file | Problem | Found |
|---|---|---|
| remigius-of-rheims | `metadata.toml` carries `default_year=533` (Remigius of Rheims, 6th-century bishop) but virtually all commentary content is attributed to Remigius of Auxerre (841-908) in patristic scholarship. Likely a naming collision at ingest. OCD-side: all 196 entries rerouted to `remigius-of-auxerre` via `REROUTE_AUTHOR` in `church_fathers.py`; upstream directory name still wrong. | 2026-04-15 |
| athanasius-of-alexandria | Entries `Ezra.1.1.unknown`, `Neh.1.1.unknown`, and `Song.1.1.unknown` contain content from the *Synopsis Scripturae Sacrae* (CPG 2249), a work universally attributed to Pseudo-Athanasius, not the historical Athanasius of Alexandria. The Ezra and Neh TOML quotes begin with bracketed labels "[Synopsis on Ezra]" and "[Synopsis on Nehemiah]"; the Song.1.1 quote is the same genre. The work is dated no earlier than the 6th century and contradicts Athanasius's authentic 39th Festal Letter. These entries should be in `pseudo-athanasius.json`, not `athanasius-of-alexandria.json`. Source: Roger Pearse blog 2018-09-18 citing CPG 2249. | 2026-04-23 |
| jerome | `Mark.1.11.unknown` (TOML: `Mark 1_11.toml`) -- the quote "Again, the Holy Ghost came down in the shape of a dove, because in the Canticles it is sung of the Church" (both paragraphs) is attributed to **PSEUDO-JEROME** in Aquinas's *Catena Aurea* on Mark Chapter 1, which is the known source for this database's Mark extracts. The Catena Aurea explicitly labels both the dove/Canticles paragraph and the "Morally also it may be interpreted...fleeting world" paragraph as PSEUDO-JEROME, not Jerome. Verified against: `https://raw.githubusercontent.com/HistoricalChristianFaith/Writings-Database/master/Thomas%20Aquinas/Catena%20Aurea/Commentary%20on%20Mark/Chapter%201.html` -- search for "Again, the Holy Ghost came down". | 2026-04-23 |
| jerome | `Mark.15.32.unknown` (TOML: `Mark 15_32.toml`) -- the quote "The foal of Judah has been tied to the vine, and his clothes dyed in the blood of the grape, and the kids tear the vine, blaspheming Christ, and wagging their heads" is attributed to **PSEUDO-JEROME** in Aquinas's *Catena Aurea* on Mark Chapter 15, verse 32. Verified against: `https://raw.githubusercontent.com/HistoricalChristianFaith/Writings-Database/master/Thomas%20Aquinas/Catena%20Aurea/Commentary%20on%20Mark/Chapter%2015.html` -- search for "foal of Judah". Both entries (`Mark.1.11.unknown` and `Mark.15.32.unknown`) were filed under `jerome` but belong under `pseudo-jerome` or should be left unattributed. | 2026-04-23 |

Effect: author dates, biographical notes, and any era-based filtering using
Remigius of Rheims will carry the wrong century. Content itself is Catena
Aurea excerpts via Aquinas, so source_title is correct regardless.

### Truncated / malformed quote text

| Author | Entry ID | Problem | Found |
|---|---|---|---|
| tatian-the-assyrian | `Mark.9.48.unknown` | Quote text "With which he careth for. / us, to appear" is <10 words, visibly truncated or garbled. Source attribution not possible. | 2026-04-15 |

Effect: entry left blank. Upstream re-extract needed.

## CCEL (Expositor's Bible)

### Invalid osisRef cross-references (Plummer volumes)

Source: `https://www.ccel.org/ccel/plummer/expositorjamesjude.xml`

| Volume | osisRef in XML | Correct ref (if known) | Found |
|---|---|---|---|
| plummer/expositorjamesjude | `Matt.42.31` | Unknown — xlii (42) exceeds Matt's 28 chapters; likely typo for "xii. 31" (Matt 12:31) but unverifiable without 1891 ed. | 2026-06-17 |
| plummer/expositorjamesjude | `Ps.30.28` | Unknown — Ps.30 has 12 verses; verse 28 cannot exist; unverifiable. | 2026-06-17 |

Both refs dropped via `_CCEL_OSISREF_CORRECTIONS` in `ccel_expositors_bible.py`.

## Internet Archive

### NSH-main — page_numbers metadata incomplete across all 13 volumes

IA item: `NewSchaffHerzogEncyclopediaOfReligious`

The `page_numbers` field in every NSH-main volume scandata XML omits the first
several body pages at the front of each volume. The scanner crew assigned page
numbers starting from a later leaf than the actual first encyclopedia article,
leaving the opening body pages with no leaf-to-page mapping. The ABBYY .gz
OCR is intact for all leaves; only the IA-supplied page-number metadata is
incomplete.

Effect: any pipeline driven by IA `page_numbers` (e.g. manifest-based OCR
sidecar generation) silently drops the unmapped leaves. Skip-rate warnings
fired for every volume at 5.7–16.2%. See
`research/2026-05-26-vol-1-skipped-pages-incident.md` for full diagnosis.

Local manifests patched for all 13 volumes (vol 1: 2026-05-27; vols 2–13:
2026-05-28). 94 body pages recovered in total. Upstream IA metadata still
wrong for all volumes. Vol 4 actual gap was leaves 19–25 (not 21–25 as
initially estimated); vol 13 actual gap was leaves 17–25 (not 18–25).

Verified 2026-05-27 by OCR inspection of leaf-index sidecars generated during
re-parse. All body-page losses confirmed by running-header text (THE NEW
SCHAFF-HERZOG / RELIGIOUS ENCYCLOPEDIA).

| Vol | IA volume file | Manifest gap | Body pages lost | First lost article | Last article before manifest |
|-----|---------------|-------------|-----------------|---------------------|------------------------------|
| 1 | `01.NewSchaffHerzogEncycReligKnowl.v1.Jackson.Sherman.Gilmore.1909` | leaves 37–45 missing | 9 (patched 2026-05-27) | AACHEN (p.1) | ABELARD (p.9) |
| 2 | `02.NewSchaffHerzogEncycReligKnowl.v2.Jackson.Sherman.Gilmore.1909` | leaves 23–30 missing | 8 (patched 2026-05-28) | BASILICA | BAUR |
| 3 | `03.NewSchaffHerzogEncycReligKnowl.v3.1909.Jackson.Sherman.Gilmore.1909` | leaves 23–31 missing | 9 (patched 2026-05-28) | CHAMIER | CHAPTER |
| 4 | `04.NewSchaffHerzogEncycReligKnowl.BibliogApend.v1-4.v4.Jackson.Sherman.Gilmore.1909` | leaves 19–25 missing | 7 (patched 2026-05-28) | DRAGON | DROSTE-VISCHERING |
| 5 | `05.NewSchaffHerzogEncycReligKnowl.v5.Jackson.Sherman.Gilmore.1909` | leaves 24–32 missing | 9 (patched 2026-05-28) | GOAR, SAINT | GOD |
| 6 | `06.NewSchaffHerzogEncycReligKnowl.v6.Jackson.Sherman.Gilmore.1909` | leaves 21–29 missing | 9 (patched 2026-05-28) | INNOCENTS, FEAST OF THE HOLY | INSCRIPTIONS |
| 7 | `07.NewSchaffHerzogEncycReligKnowl.v7.Jackson.Sherman.Gilmore.1909` | leaves 25–26 missing | 2 (patched 2026-05-28) | LIUTPRAND | LIVINGSTONE |
| 8 | `08.NewSchaffHerzogEncycReligKnowl.v8.Jackson.Sherman.Gilmore.1909` | leaves 23–31 missing | 9 (patched 2026-05-28) | MORALITY | MORMONS |
| 9 | `09.NewSchaffHerzogEncyc.ReligKnowl.v9.Jackson.Sherman.Gilmore.1909` | leaves 24–30 missing | 7 (patched 2026-05-28) | PETRI, LARS AND OLAV | PFLUG |
| 10 | `10.NewSchaffHerzogEncyc.ReligKnowl.v10.Jackson.Sherman.Gilmore.1909` | leaves 25–31 missing | 7 (patched 2026-05-28) | REUSCH | REVELATION |
| 11 | `11.NewSchaffHerzogEncyc.ReligKnowl.v11.Jackson.Sherman.Gilmore.1911` | leaves 28–36 missing | 9 (patched 2026-05-28) | SON OF GOD | SORCERY AND SOOTHSAYING |
| 12 | `12.NewSchaffHerzogEncyc.ReligKnowl.v12.Jackson.Sherman.Gilmore.1912` | leaves 37–45 missing | 9 (patched 2026-05-28) | TRENCH, RICHARD C. | TRIBAL AND CULTIC MYSTERIES |
| 13 | `13.NewSchaffHerzogEncyc.ReligKnowl.Index.v13.Jackson.Sherman.Gilmore.1914` | leaves 17–25 missing | 9 (patched 2026-05-28, index) | A-entries (ABULIA, AGRIPPA area) | ANGLICAN APOSTOLIC COUNCIL area |

**Vol 1 also has a duplicate row**: leaf 64 maps to both page 96 and page 97,
producing non-monotonic leaf ordering around pages 95–98. All other volumes
have clean leaf ordering within their captured page range (though several have
small leaf gaps at mid-volume blank or chart pages).

Estimated total front-matter boundary loss across the corpus: ~94 body pages.

### NSH-main vol 2 — scan gap: pages 254–255 absent from ABBYY .gz

IA item: `NewSchaffHerzogEncyclopediaOfReligious`, vol 2 file
`02.NewSchaffHerzogEncycReligKnowl.v2.Jackson.Sherman.Gilmore.1909`

The ABBYY .gz for vol 2 has no leaves corresponding to printed pages 254–255.
Leaf 0274 = page 252 and leaf 0275 = page 253 are present; leaf 0276 = page 256
immediately follows with no intervening leaves for pages 254–255. Pages 254–255
likely correspond to a fold-out plate or illustration spread that was physically
skipped during scanning. The OCR data for those two pages is not present in any
IA derivative and is not recoverable from existing source files. Leaf 0275 (page
253, articles Brandenburg/Brastow area) was missing from IA's page_numbers
metadata and patched into the local manifest 2026-05-28.

Found 2026-05-28 during mid-volume gap investigation.

### NSH-main vol 10 — scan defect: foreign pages replace pp.343–367

IA item: `NewSchaffHerzogEncyclopediaOfReligious`, vol 10 file
`10.NewSchaffHerzogEncyc.ReligKnowl.v10.Jackson.Sherman.Gilmore.1909`

The ABBYY .gz for vol 10 contains 21 leaves (ia_leaf_id 0367–0387) that carry
page numbers 843–873 from a different volume (likely vol 11 or an adjacent
scan). These leaves appear between vol 10's page 342 (leaf 0366) and page 368
(leaf 0388), displacing the original leaves that should contain vol 10 pages
343–367 (~25 body pages). The displaced pages cover encyclopedia articles in
the R-range (around REVIVAL, REWARD, RHETORIC area based on surrounding page
numbers). Found 2026-05-27 via manifest validation gap warning.

## Reporting status

NSH-main page_numbers defect drafted 2026-05-26 (see
`research/2026-05-26-ia-bug-report-nsh-main-page-numbers.md`); other entries
not yet reported.
