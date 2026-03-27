# Devotional Source Investigation
**Date:** 2026-03-27
**Session type:** Research only — no bulk downloading performed
**Investigator:** Claude Code (Sonnet 4.6)

---

## 1. Decision Brief

| Devotional | Verdict | Best Source |
|---|---|---|
| Morning & Evening (Spurgeon) | **Go** — PD confirmed | SWORD module `SME` via CrossWire download servlet |
| Daily Light on the Daily Path | **Go** — PD confirmed | SWORD module `Daily` via CrossWire download servlet |
| Faith's Checkbook (Spurgeon) | **Go** — PD confirmed | CCEL EPUB (contact required for redistribution) or Internet Archive scan |
| Imitation of Christ (Kempis) | **Go** — PD confirmed | Project Gutenberg #26222 (clean text, no permission needed) |
| My Utmost for His Highest | **Hard stop — NOT public domain** | US first publication 1935; copyright renewed 1963; PD date ~2030 |
| Streams in the Desert (1925) | **Conditional** — PD likely but verify | Internet Archive has it; but both IA items are OCR-dependent scans. Copyright status of the 1925 edition is strongly supported by pre-1928 publication, but the specific issue of whether any copyright renewal was filed needs a Stanford/Copyright Office database check |

**Top recommendation for SWORD path:** Download `SME` and `Daily` modules using the CrossWire download servlet (not the FTP raw modules path, which is robots.txt Disallowed). Use `diatheke` CLI (installed via libsword-dev) to extract all entries. pysword explicitly does NOT support devotional modules.

**Top recommendation for non-SWORD path:** Project Gutenberg for Imitation of Christ; CCEL EPUB + contact for permission for Faith's Checkbook; Internet Archive for Streams 1925 (with OCR cleanup needed).

---

## 2. Per-Devotional Findings

### Spurgeon's Morning and Evening

| Field | Detail |
|---|---|
| Copyright status | Public domain — confirmed |
| Author death | 1892 |
| Publication | 1866 (UK) |
| SWORD module | `SME` — module type: Daily Devotional |
| SWORD license | "Public Domain" (stated explicitly on module info page) |
| Source provenance | CCEL text, contributed by Logos Bible Software |
| Module version | 1.7 (2010-06-29) |
| Install size | 566.82 KB |
| Format | SWORD rawld/zld (Daily Devotional type); keys encoded as `$$$mm.dd` |
| Date-keyed? | Yes — 730 entries (AM + PM for each calendar day) |
| CCEL availability | Yes — HTML, PDF, EPUB at ccel.org/ccel/spurgeon/morneve |
| Internet Archive | Multiple scan versions, also Librivox audio |
| Blue Letter Bible | Hosts it at /devotionals/me/ — no stated bulk download licence; not a viable structured source |
| brandonstaggs.com | Per-entry HTML at MM-DD-AM.html / MM-DD-PM.html — no license stated, source unclear, not viable |
| Notes | The SWORD module is the cleanest structured source. Text originated at CCEL from a Logos donation. CCEL requires contact for commercial republication but the underlying text is PD. The SWORD module is licensed Public Domain with no restrictions stated. |

---

### Daily Light on the Daily Path

| Field | Detail |
|---|---|
| Copyright status | Public domain — confirmed ("Public Domain -- Copy Freely" stated in module) |
| Author | Jonathan Bagster (1813-1872) and family members |
| Publication | 1875 (original); entries are purely scripture compilations |
| SWORD module | `Daily` — module type: Daily Devotional |
| SWORD license | "Public Domain" (stated explicitly) |
| Module version | 1.0 (2002-01-01) |
| Install size | 1012.56 KB |
| Date-keyed? | Yes — 730 entries (AM + PM for each calendar day) |
| Notes | Larger install size than SME likely because it includes full scripture passages rather than commentary. No prose — entirely scripture compilations, which further removes copyright risk. |

---

### Faith's Checkbook (Spurgeon)

| Field | Detail |
|---|---|
| Copyright status | Public domain — confirmed |
| Author death | 1892 |
| Publication | 1888 (UK) |
| SWORD module | Not listed in CrossWire's official devotional repository (only 3 English modules: DBD, Daily, SME) |
| CCEL | Available — HTML, PDF, EPUB at ccel.org/ccel/spurgeon/checkbook |
| CCEL licence | "May be used for personal, educational, or non-profit purposes. Contact us for permission to republish." This is a CCEL website restriction, not a restriction on the underlying PD text. |
| Internet Archive | Multiple scan versions: `faithscheckbookd0000spur`, `faithscheckbook0000spur`, and the original at archive.spurgeon.org/fcb/ |
| archive.spurgeon.org | Clean HTML at archive.spurgeon.org/fcb/fcb-bod.htm — robots.txt not checked during this session |
| Gutenberg | Not found as standalone PG ebook |
| Date-keyed? | Yes — 366 entries (leap-year inclusive daily format) |
| Format concern | CCEL only offers PDF, EPUB, and read-online. No raw XML/ThML download exposed. Extraction from EPUB is feasible (EPUB is zip of HTML). |
| Notes | The cleanest approach: download the CCEL EPUB (public domain text, CCEL's restriction is on their website edition), extract HTML chapters, parse into date-keyed entries. Or use the archive.spurgeon.org HTML (check robots.txt first). |

---

### The Imitation of Christ (Thomas a Kempis)

| Field | Detail |
|---|---|
| Copyright status | Public domain — confirmed (c.1427, author died 1471) |
| SWORD module | Not in CrossWire devotional list |
| Project Gutenberg | **Ebook #26222** — clean text, no restrictions |
| Project Gutenberg | Also at #1653 (older digitisation) |
| CCEL | Available at ccel.org/ccel/kempis/imitation |
| Date-keyed? | No — structured as 4 books with chapters, not 365 daily entries. Would require editorial curation to create a 365-day reading plan from it. |
| Notes | Not strictly a devotional in the date-keyed sense. Gutenberg text is the cleanest machine-readable source. Worth noting for future "structured classics" track, but requires date-assignment work before it fits the devotional dataset schema. |

---

### My Utmost for His Highest (Oswald Chambers)

| Field | Detail |
|---|---|
| Copyright status | **NOT public domain in the US** |
| Author death | 1917 |
| UK first publication | 1927 (compiled by wife Biddy Chambers from lecture notes) |
| **US first publication** | **1935** (Dodd, Mead & Company) |
| Copyright renewal | Renewed 1963 by Oswald Chambers Publications Association Ltd |
| US public domain date | Not before 2030 (95 years from 1935 US publication) |
| Internet Archive | Has copies but hosting appears to be without explicit license — likely a rights oversight, not a permission |
| utmost.org | Official website operated by Discovery House / OCPA; current copyrighted edition |
| Verdict | **Hard stop.** The UK 1927 date is irrelevant — US copyright law applies to the US first publication (1935). The copyright was actively renewed in 1963. Do not use. |

---

### Streams in the Desert (Mrs. Cowman)

| Field | Detail |
|---|---|
| Copyright status | **Likely public domain, but needs database verification** |
| Author | Lettie B. Cowman (1870-1960), published as "Mrs. Charles E. Cowman" |
| First publication | 1925, Oriental Missionary Society, Los Angeles, CA |
| US PD rule | Works published before 1928 are PD if copyright was not renewed or if renewal was not filed |
| Copyright renewals | 1953 and 1965 renewals listed (these cover revised/updated editions, NOT the 1925 original) |
| Subsequent editions | 1953 revised edition (Cowman Publications, Inc.) and later Zondervan editions — these are separately copyrighted |
| Internet Archive item 1 | `streamsindesert10000lett` — published by "Innovative Eggz LLC" (modern reprint); in `printdisabled` collection (controlled digital lending); EPUB/PDF are LCP-locked. **Not freely downloadable.** |
| Internet Archive item 2 | `streamsinthedesert_202004` — details not fully accessible during this session; likely a scan |
| Internet Archive item 3 | `streamsindesert0001mrsc_l2y1` — additional scan version |
| Format concern | All Internet Archive items appear to be OCR'd scans, not clean text |
| Date-keyed? | Yes — 366 entries (Jan 1 through Dec 31 with one extra) |
| Action required | **Before any use:** Run a Stanford Copyright Renewal Database search (copyright.columbia.edu) or US Copyright Office records search for "Streams in the Desert" with 1925–1955 publication range. Confirm no renewal was filed for the 1925 first edition specifically. The 1953 and 1965 renewals almost certainly cover revised editions only. |
| Notes | Even if PD confirmed, all available digital text is OCR-derived — expect errors, especially in scripture references. A manual clean-up pass will be needed. |

---

## 3. SWORD Tooling Assessment

### Complete list of CrossWire official English devotional modules (as of 2026-03-27)

There are only **3 English devotional modules** in the CrossWire main repository:

| Module ID | Title | License |
|---|---|---|
| `SME` | C. H. Spurgeon's Morning and Evening: Daily Readings | Public Domain |
| `Daily` | Jonathan Bagster's Daily Light on the Daily Path | Public Domain |
| `DBD` | Day By Day By Grace — Bob Hoekstra | Unknown (modern author; likely restricted) |

Non-English modules present: `FreLitCal2025`, `FreLitCal2026` (French Catholic liturgical calendars), `PorLitCal2020`–`2024` (Portuguese liturgical calendars). Faith's Checkbook is **not** in the CrossWire official devotional repository.

### robots.txt findings — crosswire.org

```
User-agent: *
Crawl-delay: 30
Disallow: /ftpmirror/pub/sword/raw/modules/    <-- bulk FTP module directory BLOCKED
Disallow: /ftpmirror/pub/sword/iso/
```

The module download servlet (`/sword/servlet/SwordMod.Verify?modName=SME&pkgType=raw`) is **not disallowed**. This is the per-module download link used by the website and by SWORD Install Managers. Downloading individual modules via this URL is the intended method.

### Python tooling — assessment

| Tool | Status | Devotional support | Verdict |
|---|---|---|---|
| **pysword** (PyPI `pysword==0.2.8`) | Last release May 2022; MIT licence; maintained by Tomas Groth at gitlab.com/tgc-dk/pysword | **Explicitly no** — README states "Read SWORD bibles (not commentaries etc.)" Only supports Bible module formats (ztext, ztext4, rawtext, rawtext4) | Do not use for devotionals |
| **diatheke** (CLI, part of libsword) | Actively maintained as part of SWORD engine; available on Linux via `apt install diatheke` | **Yes** — diatheke can query any installed module type including Daily Devotionals by date key | Recommended approach |
| **sword-converter** (github.com/alphapapa/sword-converter) | Abandoned — last commit Jan 2018; C++ module-to-json.cpp wraps full SWORD library | Unknown; C++ dependency makes it brittle | Not recommended |
| **python-sword** (SWIG bindings) | Part of libsword source; not packaged separately for pip | Yes — full SWORD API access | Viable but complex to install on Windows |
| **sword-module-converter** (github.com/adedayo/sword-module-converter) | Go binary, converts to YAML/OSIS | Unclear | Not Python; secondary option |

### Recommended conversion approach

1. Install SWORD engine on Linux (or WSL): `sudo apt install sword-tools`
2. Download SME and Daily modules using the CrossWire servlet URL (respecting the 30-second crawl delay from robots.txt — use one request per module, not a scraper loop)
3. Use `diatheke` to extract all 730 entries per module:
   ```bash
   for month in 01 02 03 04 05 06 07 08 09 10 11 12; do
     for day in ...; do
       diatheke -b SME -k "$month.$day" >> output.txt
     done
   done
   ```
4. Parse the output into JSON. Diatheke output format is plain text with the key prepended.

**Alternative (no SWORD engine install):** The SWORD module zip files are zlib-compressed rawld format. The internal data files can be parsed directly — the key format is `$$$mm.dd` per the CrossWire wiki. This approach requires writing a binary parser but has no dependencies. Given that pysword's source code for Bible modules is available and the rawld format is documented, this is a realistic option.

### Module licensing for redistribution

Both `SME` and `Daily` are explicitly licensed "Public Domain" in their module conf files. CrossWire's copyright page indicates that modules carry their own licensing. Public Domain modules have no redistribution restrictions. Converting to JSON and publishing in an open dataset is permissible.

`DBD` (Day By Day By Grace, Bob Hoekstra) is a modern work by a living author. Even if CrossWire distributes it, the underlying text is almost certainly copyrighted. Do not use.

---

## 4. Copyright Uncertainty Items

These require human legal judgment or active verification before use:

### 4a. Streams in the Desert (1925) — MEDIUM RISK

**The uncertainty:** The 1925 first edition appears to be pre-1928 and therefore PD in the US. However:
- Copyright renewals were filed for the 1953 and 1965 editions by Cowman Publications
- It is not confirmed whether the original 1925 copyright was registered and then NOT renewed (which would confirm PD), or whether the 1953 renewal was filed as a renewal of the 1925 copyright rather than as a new copyright for a revised edition

**Action required:** Search the US Copyright Office renewal records (copyright.gov/records) or Stanford's copyright renewal database for "Streams in the Desert" with registration dates 1925-1952. If no renewal appears for the 1925 original registration, it is PD. If a renewal appears, more analysis is needed.

**Risk if wrong:** Zondervan (now part of HarperCollins) is the current rights holder for modern editions and actively licenses the work. They would have standing to pursue infringement if the 1925 edition is not confirmed PD.

### 4b. CCEL redistribution restriction

**The uncertainty:** CCEL's copyright policy states that their editions "may be used for personal, educational, or non-profit purposes" and requires contact for commercial or republication use. This applies to CCEL's specific edition (their digitisation, formatting, possibly introductory text) — not to the underlying PD text.

**Action required:** Determine whether OCD will publish the data commercially or non-commercially. If non-commercial, CCEL's own restriction likely permits use. For a fully open (CC0 or similar) dataset meant to be embedded in commercial products, contact CCEL at their listed contact address. The PD text itself is not restricted — only CCEL's edition. This can be resolved by taking the text from a different source (Internet Archive, Project Gutenberg, or SWORD module).

### 4c. Internet Archive scan quality for Streams in the Desert

**The uncertainty:** The IA items identified are all OCR'd scans from physical books. The `streamsindesert10000lett` item is from "Innovative Eggz LLC" — a modern print-on-demand reprint publisher — and is in the `printdisabled` collection (controlled digital lending). The OCR text from this item may contain the publisher's copyright notice even if the underlying 1925 text is PD.

**Action required:** Prefer a scan of an actual 1925 original printing over a modern reprint scan. The `streamsinthedesert_202004` item (uploaded 2020, different uploader) may be a scan of an original — this item's details were not fully accessible during this session and should be inspected manually.

---

## 5. Recommended Download Sequence

Priority order, accounting for rights clarity and format quality:

1. **Spurgeon's Morning and Evening (SME)** — highest priority, cleanest source
   - Method: Single ZIP download from `https://www.crosswire.org/sword/servlet/SwordMod.Verify?modName=SME&pkgType=raw`
   - Extract via `diatheke` or custom rawld parser
   - No permission needed; Public Domain confirmed

2. **Daily Light on the Daily Path (Daily)** — same process
   - Method: `https://www.crosswire.org/sword/servlet/SwordMod.Verify?modName=Daily&pkgType=raw`
   - No permission needed; Public Domain confirmed

3. **The Imitation of Christ** — straightforward
   - Method: `wget https://www.gutenberg.org/ebooks/26222.txt.utf-8` or use Gutenberg's API
   - No permission needed; clean text
   - Requires editorial work to create date-keyed reading plan

4. **Faith's Checkbook** — moderate effort
   - Method: Download CCEL EPUB from `https://ccel.org/ccel/s/spurgeon/checkbook/cache/checkbook.epub`
   - The EPUB is a zip file containing HTML chapters; parse into date-keyed JSON
   - For open redistribution: consider using the Internet Archive scan or archive.spurgeon.org as the source text (check robots.txt on archive.spurgeon.org first) to avoid needing CCEL permission
   - Alternatively, contact CCEL first — they are responsive and this is a non-commercial project

5. **Streams in the Desert (1925)** — do copyright verification first
   - Block on Step 4a (copyright renewal database search) before proceeding
   - If PD confirmed: locate a 1925 original scan on Internet Archive (not the `streamsindesert10000lett` CDL item)
   - OCR cleanup pass will be required before structured parsing

6. **My Utmost for His Highest** — do not proceed
   - Not public domain until ~2030
   - No further investigation needed

---

## Sources Consulted

- CrossWire SWORD devotional module list: crosswire.org/sword/modules/ModDisp.jsp?modType=Devotionals (inspected live)
- SME module info: crosswire.org/sword/modules/ModInfo.jsp?modName=SME (inspected live)
- Daily module info: crosswire.org/sword/modules/ModInfo.jsp?modName=Daily (inspected live)
- crosswire.org/robots.txt (inspected live)
- pysword PyPI page: pypi.org/project/pysword/ (inspected live)
- CCEL copyright policy: ccel.org/about/copyright.html (inspected live)
- CCEL Faith's Checkbook: ccel.org/ccel/spurgeon/checkbook.html (inspected live)
- CCEL Daily Meditations: ccel.org/meditate (inspected live)
- Internet Archive Streams in the Desert (1925): archive.org/details/streamsindesert10000lett (inspected live)
- alphapapa/sword-converter GitHub: github.com/alphapapa/sword-converter (inspected live — abandoned 2018)
- Wikipedia: My Utmost for His Highest (US publication date, copyright renewal)
- WebSearch: multiple queries on copyright status, Python tooling, Gutenberg availability
