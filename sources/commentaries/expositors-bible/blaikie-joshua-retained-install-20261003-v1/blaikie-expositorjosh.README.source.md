# Retained source: The Expositor's Bible: The Book of Joshua

Sourced via CCEL.org.

Retained authority: raw/ccel/expositors-bible/blaikie_expositorjosh.xml; SHA-256 7a2be4c01ca4ed8ecf37aa6905a161c126ac8cc4752e00448126ae363d2139b3; 823168 bytes.

Primary source author: W.G. Blaikie. Series editor: William Robertson Nicoll.

Literal source printed-edition statement: London: Hodder and Stoughton, 1893..

Literal DC.Rights: [empty in retained source]. This source field is not rights clearance.

Qualified current LIB036 converter-only replay retains the exact downloaded bytes and original-reading feature graph. September11 candidate path is access denied; historical package recovery and old oracle validation are not claimed. All historical correction alternatives remain qualified; raw readings are retained.

Complete authored Book of Joshua from its one already acquired CCEL electronic witness: title page, all Chapters I through XXXIII including authored introduction, generated indexes, notes and verse. Samuel and author/series completeness are excluded. Human review, print collation, rights clearance and publication remain separate; no new acquisition.

Chapter I is substantive authored introduction and remains in the body; only title page i is front, and index xxxv is back. All source readable content remains in original order. Source h1 through h6 preserve exact heading level as source-level paragraphs. Notes, verse lines, page numbers, lists, inline styles and every literal source attribute retain fields, order and attachment. The 22 administrative comments retain exact source fields/positions; their whitespace-only tails join adjacent actual TEI carriers reversibly.

All 40 relative query links retain literal href readings and the exact primary acquired CCEL HTML URL as per-ref xml:base. Two absent source next/prev toc destinations remain explicit typed unresolved gaps; no destination is invented. The complete Joshua source contains no table or image elements and no historical text-correction proposals; no raw reading is replaced. Literal source header fields, CSS, XML declaration and stylesheet processing instructions remain visible and accounted.

Bennett mapping and checker implementations were inspected and used as separately maintained ancestors; independence is not blind. The current checker independently derives all readable fields and hierarchy from stdlib raw XML, corroborates all raw fields with strict lxml, and inverses the whole raw body from the actual TEI. No browser/CSS visual equivalence or print collation is claimed.

## Retained CCEL permission evidence

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
