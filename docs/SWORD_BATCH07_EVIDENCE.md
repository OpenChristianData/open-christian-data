# Batch 07 SWORD upstream evidence

**Date:** 2026-07-16  
**Decision:** all three inventory entries remain `do-not-migrate`.  
**Scope:** provenance and TEI routing only. No TEI was built from a SWORD binary.

This record is the cold-session evidence for `sword-commentary`,
`sword-devotional`, and `sword-naves-topical`. A SWORD module may contain markup
that originated in an upstream XML source, but the packaged zCom/rawLD/zLD
binary is still a downstream projection. It is not an acceptable source for a
new authoritative TEI IR.

## Primary artifacts read

- `sources/commentaries/{barnes,calvin,wesley}/config.json`
- `sources/devotionals/daily-light/config.json`
- `raw/sword_modules/{Barnes,CalvinCommentaries,Wesley,Daily}/mods.d/*.conf`
- `raw/naves_topical/mods.d/nave.conf`
- `build/parsers/sword_commentary.py`
- `build/parsers/sword_devotional.py`
- `build/parsers/naves_topical.py`
- the existing outputs under `data/commentaries/`, `data/devotionals/`, and
  `data/topical-reference/`
- `raw/ccel/calvin-commentaries/calvin-commentaries.manifest.json`,
  `commentaries.xml`, and `calcom01.xml` through `calcom45.xml`
- `research/commentary/SOURCE_INVESTIGATION.md` and
  `docs/sources/ccel-permission.md` for named, non-acquired routes

## Resource decisions

### `sword-commentary`

**Classification: confirmed `do-not-migrate`.** The three source configs call
the inputs SWORD zCom modules. The module metadata identifies Barnes and Wesley
as ThML and Calvin as OSIS, while Calvin's `.conf` says the module was converted
to SWORD format from Christian Classics Ethereal Library material. The parser
reads compressed zCom BZS/BZV/BZZ files and `clean_markup()` strips all remaining
XML/HTML tags after extracting selected cross-references. The output therefore
does not carry the source's note, language, emphasis, table, or paragraph
boundaries as TEI structure.

The read-only parser dry-runs produced these record counts:

| module | nonempty SWORD records | mapped output records | mapped book names |
|---|---:|---:|---:|
| Barnes | 7,322 | 7,322 | 27 |
| Calvin | 13,338 | 13,338 | 49 |
| Wesley | 17,564 | 17,564 | 66 |

The Calvin number needs a qualification: `raw/sword_modules/CalvinCommentaries/
mods.d/calvincommentaries.conf` and `sources/commentaries/calvin/config.json`
describe a 47-book set and say Acts is absent, but the current position mapping
also labels nonempty records as Judges and Acts. The 49-book mapped count is
therefore an observed parser result, not a settled coverage claim. It is logged
as a successor-queue mapping bug below.

**Upstream state:** mixed within this family.

- **Calvin — acquired on disk:** `raw/ccel/calvin-commentaries/calcom01.xml`
  through `calcom45.xml`, plus the CCEL catalogue and acquisition manifest.
  The manifest has 45 component paths, all 45 exist, and all 45 component XML
  files declare `DC.Rights` as Public Domain. The future IR starts from those
  CCEL component XML files and their manifest, not from
  `raw/sword_modules/CalvinCommentaries/`.
- **Barnes — identified but not acquired:** the local source investigation
  names the CCEL Barnes NT ThML/text route
  (`https://ccel.org/ccel/b/barnes/ntnotes/cache/ntnotes.txt`) and Internet
  Archive scans for Barnes OT. No Barnes upstream XML/text artifact was found
  in the repository's raw tree. A future IR for the current Barnes NT scope
  must start from a rights- and edition-verified upstream text, not the zCom
  binary.
- **Wesley — identified but not acquired:** the local source investigation
  names the complete Sacred Texts HTML route and records its one-copy-per-day
  restriction. No Wesley Notes upstream artifact was found in the raw tree.
  A future IR must begin with a specifically acquired and rights-cleared
  source whose edition identity is verified; the SWORD binary is not that
  starting point.

### `sword-devotional`

**Classification: confirmed `do-not-migrate`.** `daily.conf` identifies a
`RawLD` module with `SourceType=ThML`; the parser reads `daily.idx` and
`daily.dat`, splits each binary entry into Morning and Evening, extracts
`scripRef` values, then strips every remaining tag before writing plain
`content_blocks`. The packaged rawLD record is consequently a projection, even
though its payload originated as ThML.

**Upstream state: identified but not acquired (site-level route only).** The
module `.conf` names `http://www.bf.org/` as `TextSource`, but no specific
upstream file or edition-matched raw artifact was found on disk. The repository
also has a general instruction to check CCEL for future devotional sources, not
a Daily Light acquisition. Availability of a usable Daily Light upstream is
therefore not confirmed. A future IR must start from a specifically acquired,
rights-cleared ThML or equivalent raw source with edition provenance.

The raw index has 367 slots: one header plus 366 nonempty day entries. The
current output has 732 records: 366 morning and 366 evening. The raw entries
contain 1,218 opening `scripRef` tags and 20,313 `br` tags; the output contains
1,218 cross-reference objects and no residual markup in `content_blocks`.
The reference correction is complete, but it does not turn the rawLD binary
into an IR source.

### `sword-naves-topical`

**Classification: confirmed `do-not-migrate`.** The `.conf` calls the module
`zLD` and labels its payload `SourceType=TEI`, but the parser reads only
`dict.idx`, `dict.dat`, `dict.zdx`, and `dict.zdt`. It extracts selected topic,
subtopic, Scripture-reference, and related-topic values; it does not preserve
the source TEI element structure. The word “TEI” in the module metadata
describes the embedded content's origin/markup, not a disk-resident upstream
TEI file.

**Upstream state: identified but not acquired.** `raw/naves_topical/mods.d/nave.conf`
names the specific CCEL route `https://ccel.org/ccel/n/nave/bible.xml` and says
the 2021 source was from CCEL. No CCEL Nave XML file was found on disk. A future
IR must start from that named upstream route only after the exact source is
acquired, hash-pinned, and rights/edition provenance is verified; it must not
start from `Nave.zip` or its extracted zLD files.

The raw index contains 5,322 entries and all 5,322 were extracted without a
malformed or skipped index record. The extracted XML contains 5,322 `entryFree`
and 5,322 `def` elements, 15,019 subtopic divisions, 77,935 opening
`ref osisRef` tags, and 4,368 related-topic targets. The current output contains
5,322 entries, 15,019 subtopics, 76,957 Scripture-reference objects, and 4,368
related-topic links. The 978-reference difference is real parser loss: the
parser logs and code path explicitly drop references before the first arrow in
an entry. That bug is not fixed in this evidence-only batch.

## Counts and computation

- Commentary counts came from `--dry-run` on each module and an independent
  read-only walk through the zCom reader. Raw opening-tag counts were:
  Barnes: 52,532 `<i>`; Calvin: 22,465 `<note>`, 31,300 `<foreign>`, 196,065
  `<hi>`, 7,045 `<table>`; Wesley: 4,177 `<scripRef>`. The parser's cleaned
  text had zero residual XML/HTML tags in all three walks.
- Daily Light counts came from a direct read-only scan of the rawLD index/data
  pair and the existing JSON output. The header slot is excluded from the 366
  day count; each day is split into two output periods.
- Nave counts came from a direct read-only scan using the parser's zLD block
  reader and subtopic/reference helpers, then a separate count of the existing
  JSON output. The raw `osisRef` count and emitted-reference count are reported
  separately because the parser drops pre-arrow references.
- CCEL counts came from the component manifest and a read-only XML scan of the
  45 component files. The scan found 17,283 `<note>`, 22,781 `span lang`,
  114,331 `<i>`, 24,787 `<scripRef>`, and 4,924 `<table>` opening tags.

## Calvin routing

Calvin's acquired CCEL ThML is routed to the CCEL queue, not a SWORD path. The
SWORD `.conf` and source config both establish that the SWORD module is a
conversion from CCEL; the acquired component XML, catalogue, and manifest are
the available upstream evidence. This batch records that routing and performs
no conversion. The inventory's future IR start point is the CCEL component XML
set.

## Proof conversion

No proof conversion was performed. The only acquired upstream found in this
batch is Calvin's CCEL ThML, and the inventory already routes it to the CCEL
queue. Converting it here would duplicate that queue and would violate the
batch's projection boundary.

## Out-of-scope successor items

- Audit and correct the Calvin zCom position/coverage mapping: the current
  parser dry-run produces 49 mapped book names including Acts, while the
  primary module/config metadata describes 47 books and excludes Acts.
- Decide whether the named Barnes and Wesley routes can be acquired with clear
  edition, rights, and structure provenance.
- Acquire and hash-pin the named CCEL Nave XML before any IR work.
- Fix or explicitly model the 978 Nave pre-arrow Scripture references if the
  SWORD parser remains useful for a non-IR projection.

No data JSON, parser code, TEI output, git state, or progress tracker was
changed by Batch 07.
