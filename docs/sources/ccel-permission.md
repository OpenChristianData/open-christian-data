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
