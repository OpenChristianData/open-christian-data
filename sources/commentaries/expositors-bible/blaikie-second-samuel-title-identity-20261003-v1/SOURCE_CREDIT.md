# Source credit: The Second Book of Samuel

Distinct complete authored book by W.G. Blaikie. One complete authored commentary on The Second Book of Samuel by W.G. Blaikie, within The Expositors Bible series edited by W. Robertson Nicoll. Its own titled New York A.C. Armstrong and Son 1898 title page, chapters I-XXXIII, concluding chapter and final generated indexes define this complete book. First Samuel and Joshua are distinct titled works outside this candidate; author-catalog and series completeness are not claimed.

Existing source: raw/ccel/expositors-bible/blaikie_expositor2sam.xml; SHA-256 e3397acdd20cbc7ea8ef6c81eb10407263fe1276b40973c07cd908cf4902c379; 758940 bytes. Original acquired URL: https://www.ccel.org/ccel/blaikie/expositor2sam.html.

This is an additive identity for already retained source; no download or new source process. Original author-catalog files and IDs remain unchanged. Acquisition fields, absent access-date/rights fields and old state timestamps are preserved. Its original author-cohort scope/warnings remain historical lineage, not a complete-series assertion or rights clearance.

Sourced via CCEL.org. CCEL-produced electronic files and derivatives of their formatting must not be sold; excerpts must credit CCEL.org. Exact retained permission follows.

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
