# Stokes: The Acts of the Apostles, one complete retained electronic work

One authored Acts commentary in two volumes by G.T. Stokes. Volume I Preface defines the early narrative before Paul conversion/Cornelius; Volume II Preface explicitly terminates the survey and describes this volume together with the previous one. Complete source titles, common author/editor, contents and ordered volume envelopes establish one work. Chapters and per-volume indexes are parts; The Expositors Bible is the surrounding series. No entire-author or series completeness claim.

One candidate TEI preserves both entire source volume envelopes once in order. The inherited author catalog identity and every legacy master, acceptance, source record and ID remain unchanged. Exactly 57 relative query refs receive only their original acquired volume URL as XML base; targets remain literal and no cross-volume target is invented. Every raw header field, CSS, source document prefix and full legacy accepted header remain visible in their owning volume records. All15 volumeI source-broken links remain qualified; volumeII has0. No acquisition or download.

Human review, print collation, rights and publication remain separate. Sourced via CCEL.org. Do not sell CCEL electronic files or derivatives of their formatting; exact retained permission and each source credit follow.

# Expositor's Bible source attribution

The Expositor's Bible source files used by Open Christian Data were **sourced via CCEL.org**.

CCEL confirmed that parsing its ThML/XML files for text is permitted. The underlying public-domain texts remain public domain, while CCEL's conditions apply to its files and formatting: do not sell CCEL files or derivatives of their formatting. See [CCEL's copyright policy](https://ccel.org/about/copyright.html).

This attribution does not by itself establish textual acceptance, edition identity, rights clearance, canonical IR acceptance, or publication readiness for any reconstruction candidate.


# Expositor's Bible source attribution

The Expositor's Bible source files used by Open Christian Data were **sourced via CCEL.org**.

CCEL confirmed that parsing its ThML/XML files for text is permitted. The underlying public-domain texts remain public domain, while CCEL's conditions apply to its files and formatting: do not sell CCEL files or derivatives of their formatting. See [CCEL's copyright policy](https://ccel.org/about/copyright.html).

This attribution does not by itself establish textual acceptance, edition identity, rights clearance, canonical IR acceptance, or publication readiness for any reconstruction candidate.


## Retained permission evidence

# CCEL — permission and ThML usage

## Permission

Confirmed 2026-04-01 by Quincy (CCEL): parsing ThML/XML files for text is explicitly permitted. CCEL's copyright applies to their files and formatting only — not the underlying PD texts. Restriction: do not sell CCEL files or derivatives of their formatting. Attribution appreciated (mention CCEL in publication) but not legally required.

Full policy: https://ccel.org/about/copyright.html

Attribution convention: include "sourced via CCEL.org" in dataset README/card.

## Using ThML

CCEL (ccel.org) provides ThML (Theological Markup Language) XML files for public domain Christian texts.

URL pattern: `https://www.ccel.org/ccel/{author}/{work}.xml`

Used as OCD's first devotional source (Spurgeon's Morning & Evening): `morneve.xml`, 732 entries (366 days including Feb 29). Also used as `source_url` for 8 doctrinal documents (Chalcedonian Definition, French Confession, Second Helvetic Confession, etc.).

## Why CCEL over SWORD modules

The SWORD module approach (`pysword` library) only supports Bible text modules, NOT GenBook modules like devotionals. diatheke (CrossWire CLI) could work but is hard to install on Windows. CCEL ThML XML is the practical, accessible alternative.

## Convention for new devotional sources

For future OCD devotional sources (Daily Light, Faith's Checkbook) and theological works, check CCEL first for a ThML XML version before investigating other formats. The existing `ccel_devotional.py` parser handles ThML preprocessing (entity replacement, encoding fallback) and can be adapted for other CCEL works.
