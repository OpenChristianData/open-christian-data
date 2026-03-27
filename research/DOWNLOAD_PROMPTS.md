# Open Christian Data — Download & Processing Prompts

**Created:** 2026-03-27
**Updated:** 2026-03-28 (anonymised paths, updated Creeds.json licensing)
**Purpose:** Autonomous prompts for downloading and processing Christian literature sources. Run in Claude Code sessions.

---

## Shared Preamble — Respectful Downloading Standards

Every download prompt in this file includes the following standards. They are repeated inline in each prompt so prompts are self-contained.

```
## Respectful Downloading Standards (MANDATORY)

Follow these rules for ALL web access in this session:

1. **Check robots.txt first.** Read and obey robots.txt before making any requests to a site. Document what you found.
2. **Check Terms of Service.** Look for /terms, /legal, /about pages. If ToS prohibits bulk download or redistribution, STOP and document the restriction.
3. **Prefer APIs and git clone over scraping.** If a site offers a REST API, RSS feed, or GitHub repo, use that instead of HTML scraping.
4. **Prefer bulk download endpoints.** Many sites offer archive downloads or mirror files. One request beats 1,000.
5. **2-second minimum delay between requests** to any single domain. Use `time.sleep(2)` or equivalent.
6. **Identify the project in User-Agent.** Use: `OpenChristianData/1.0 (research; open-source data project; contact: openchristiandata@gmail.com)`
7. **SHA-256 hash every downloaded file.** Record in the manifest alongside URL, file size, and download timestamp.
8. **Log all requests.** Append to `research/{category}/request_log.csv` with: timestamp, URL, HTTP status, bytes received, notes.
9. **Never re-download cached files.** Check if the file already exists locally before requesting.
10. **Copyrighted content = hard stop.** If a source mixes public domain and copyrighted content, flag for human review. Do NOT download copyrighted material.
11. **Ambiguous licensing = stop and document.** If you can't confirm a source is public domain or openly licensed, document what you found and skip it.
12. **Prefer clean text sources over OCR-dependent ones.** If a work exists as both clean text (HTML, XML, API) AND as scanned PDFs, always prefer the clean text source.
13. **Respect Crawl-delay** directives in robots.txt. If specified, use their delay instead of the 2-second minimum.
14. **Contact information.** If a site explicitly asks for contact before bulk use, document this and flag for human action.
```

---

## How to Use These Prompts

1. **Investigation prompts (INV-1 through INV-8):** COMPLETED. Reports are in `research/{category}/SOURCE_INVESTIGATION.md`.
2. **Tier 1 prompts (T1-1 through T1-5):** Process data already on disk. No network access needed. Can run in parallel.
3. **Tier 2 prompts (T2-1 through T2-3):** Simple downloads from settled sources. One session per source site.
4. **Tier 4 prompts (T4-1 through T4-4):** Longer downloads requiring rate limiting or scraping. One session per source site.
5. **DL-1:** HelloAO commentary acquisition via CLI self-host.
6. **All prompts are self-contained.** Copy-paste into a Claude Code session and run.

---

## Known Constraints (from investigations)

These apply across all prompts. Each prompt references the relevant constraints inline.

| Constraint | Detail |
|-----------|--------|
| **CCEL formatting copyright** | CCEL asserts copyright on their formatting even though underlying texts are PD. Email sent requesting permission (Tier 3). Until reply: use CCEL as verification only, prefer CrossWire/PG/IA as primary source. |
| **HelloAO API prohibition** | Docs say "do not use the API to download an entire commentary." Use `@helloao/cli` to self-host and generate static JSON locally. |
| **Sacred-texts.com ToS** | Robots permitted only to create search index or download one copy of one text per day. Use for verification only. |
| **StudyLight.org** | All materials claimed as copyrighted. Permission required for any reuse. Do not scrape. |
| **My Utmost for His Highest** | US first pub 1935, renewed 1963. Not PD until ~2030. Excluded. |
| **Valley of Vision** | Banner of Truth copyright, actively enforced. Bennett substantially reworked texts. Excluded — source Puritan prayers from originals. |
| **Heidelberg 2011 translation** | Faith Alive Christian Resources copyright. Use 1879 RCA translation instead. |
| **CPH Luther translations** | Modern Concordia Publishing House translations copyrighted. Use Bente/Dau 1921 from Project Gutenberg. |
| **Augustine Outler translation** | CCEL's Outler translation may be 20th century. Use Pusey translation (PG #3296). |
| **Athanasius Mackmurdo** | C.S. Lewis-prefaced translation is NOT PD. Use Robertson 1891 (NPNF). |
| **pysword limitation** | pysword only reads Bible modules, NOT commentaries or devotionals. Use `diatheke` CLI (via WSL/libsword) for SWORD devotional modules. |
| **Creeds.json license** | RESOLVED 2026-03-28: NonlinearFruit confirmed whole repo is Unlicense. Copyrighted scripture texts had permission obtained; Crossway ESV has general use clause. Our output uses OSIS refs only (no embedded scripture). All 43 documents are usable. |

---

## SCHEMA-0 — Review & Formalise Data Schemas

```
You are reviewing and formalising the data schemas for the Open Christian Data project before processing begins.

WORKING DIRECTORY: <repo-root>  # clone of OpenChristianData/open-christian-data

## Context

We have completed source investigations across 8 categories. Several schema issues were identified that must be resolved before processing scripts are written. This prompt creates the authoritative schema definitions the processing scripts will conform to.

## Known Schema Issues from Investigations

1. **Luther's Large Catechism is NOT Q&A** — continuous prose by topic. Needs `treatise` type: `part > chapter > paragraph`.
2. **Heidelberg Catechism** — 129 Q&A pairs grouped into 52 Lord's Days. Needs both `question_number` and `lords_day` fields.
3. **Luther's Small Catechism** — parts (Ten Commandments, Creed, Lord's Prayer, etc.), not simple sequential numbering. Needs `part > section > question > answer`.
4. **Sermons** — some are individually titled, some numbered in series, some are dated (devotionals). Schema must handle all three keying patterns.
5. **Source provenance** — every record in every category must carry provenance fields to enable correct HuggingFace licensing declaration.

## Required Provenance Fields (add to every record in every category)

```json
{
  "source_license": "cc0 | public_domain | cc_by_4.0 | unlicense",
  "source_url": "canonical URL of the input file used",
  "translation_year": 1921
}
```

## Your Task

### Step 1: Check for existing DESIGN_SPEC.md
- Look in the project root, docs/, and research/ directories for any existing schema specification file
- If found, read it and note any conflicts with the known issues listed above
- If not found, note that you are creating it from scratch

### Step 2: Formalise schemas for each category
For each of the 8 categories below, write a JSON Schema block defining the structure of a single processed record. Save all schemas to a new file: `docs/SCHEMA_SPEC.md`.

Categories to define:
- **bible_text**: book, chapter, verse, text, plus provenance fields
- **confession**: document-level metadata + chapter/article/paragraph structure
- **catechism_qa**: Q&A structure with lords_day field for Heidelberg; part/section nesting for Luther's Small
- **catechism_prose**: treatise structure (part > chapter > paragraph) for Luther's Large Catechism
- **church_fathers**: verse-keyed commentary quote with author, source_title, source_url
- **theological_work**: book/chapter/paragraph prose with title, author, translator, translation_year
- **sermon**: title, author, number (if series), scripture_ref, date (if dated), text
- **devotional**: date (MM-DD), period (AM/PM if applicable), verse_ref, text
- **prayer**: title, occasion, source (BCP 1662 / Didache / etc.), text, scripture_refs
- **reference_entry**: term, definitions array, source_dictionary, source_year
- **hymn**: title, author, year, metre, tune_name, scripture_refs, stanzas array
- **topical_reference**: topic_number, topic_name, verse_refs array, cross_refs array (Nave's)

### Step 3: Validate schemas against sample data
For each category where we already have data on disk, load one sample record and verify the schema fits:
- Creeds.json: load WSC question 1, check it fits catechism_qa schema
- Commentaries-Database: load one TOML file, check it fits church_fathers schema
- JWBickel: load one JSONL entry, check it fits reference_entry schema

### Step 4: Note conflicts
Document any cases where real data doesn't fit the proposed schema. These become open issues in the spec.

### Step 5: Write SCHEMA_SPEC.md
Save to: `docs/SCHEMA_SPEC.md`

Include:
- One JSON example per schema type showing all fields
- Required vs optional field notes
- The 3 provenance fields required in every record
- Open issues (schema gaps or conflicts found in Step 4)

## Constraints
- Use `py -3` to run any scripts
- Use only ASCII characters in print() output
- Do NOT modify any raw/ or processed/ data
```

---

## Tier 1 — Process Data on Disk (no network needed)

### T1-1: Creeds.json → Confessions & Catechisms

```
You are processing the Creeds.json repository (already cloned) into structured datasets for the Open Christian Data project.

WORKING DIRECTORY: <repo-root>  # clone of OpenChristianData/open-christian-data

## Context

The repo at `raw/Creeds.json/` contains 43 confessional documents in JSON. All are under the Unlicense (resolved 2026-03-28 with NonlinearFruit). One excluded: `shema_yisrael.json` (Jewish text, out of scope).

The JSON schema is: `{Metadata: {Title, Year, Authors, ...}, Data: [{Number, Question, Answer, Proofs}]}`. Catechisms use Q&A arrays; confessions use chapter/article arrays. Proof texts are structured as arrays of verse reference strings (e.g., `["Rom.11.36", "1Cor.10.31"]`).

## Known Schema Issues

1. **Luther's Large Catechism is NOT a Q&A document.** It is continuous theological prose organized by topic (Ten Commandments, Creed, Lord's Prayer, Baptism, Lord's Supper, Confession). If present in Creeds.json, it needs a different schema — `treatise > chapter > paragraph`, not `question > answer > proof_texts`.

2. **Heidelberg Catechism has Lord's Day groupings.** The 129 Q&A pairs are grouped into 52 Lord's Days. The output schema needs both `question_number` (1-129) AND `lords_day` (1-52).

3. **Luther's Small Catechism** is organized by parts (Ten Commandments, Creed, Lord's Prayer, Baptism, Confession, Lord's Supper), not simple sequential numbering. The parser needs to handle nested structure: `part > section > question > answer`.

4. **Translation provenance matters.** Add `translation_source` and `translation_year` fields to each document. For the Heidelberg, we need the 1879 RCA translation (PD), NOT the 2011 CRC/RCA (copyrighted).

## Your Task

### Step 1: Inventory
- List all 43 documents in the repo
- Mark which are Unlicense vs copyrighted
- Classify each as: creed, confession, catechism (Q&A), or catechism (prose)
- Check if the Heidelberg includes Lord's Day groupings
- Check if Luther's Large Catechism is present and what format it's in

### Step 2: Parse usable documents
Write a Python script (`scripts/parse_creeds_json.py`) that:
- Reads each Unlicense JSON file from `raw/Creeds.json/creeds/`
- Outputs normalized JSON to `processed/confessions/` and `processed/catechisms/`
- Splits confessions (chapter-structured) from catechisms (Q&A-structured)
- Handles the 4 schema issues above
- Adds provenance metadata: source repo, commit hash, license, parse date
- Uses `py -3` to run (not `python`)
- Uses only ASCII characters in print() output (Windows cp1252 console)

### Step 3: Validate
- Count documents processed vs expected
- Spot-check 3 documents: verify Q&A count matches expected (WSC=107, WLC=196, Heidelberg=129)
- Verify proof text arrays are preserved
- Log any parsing errors or unexpected structures

### Step 4: Create manifest
Save to: `processed/confessions/MANIFEST.md` and `processed/catechisms/MANIFEST.md`

Include: document list, entry counts, schema used, source commit hash, processing date, any documents excluded and why.

## Output
- Processed JSON files in `processed/confessions/` and `processed/catechisms/`
- Processing script in `scripts/parse_creeds_json.py`
- Manifests in each output directory
```

---

### T1-2: Commentaries-Database → Church Fathers

```
You are processing the HistoricalChristianFaith/Commentaries-Database repository (already cloned) into a structured Church Fathers dataset for the Open Christian Data project.

WORKING DIRECTORY: <repo-root>  # clone of OpenChristianData/open-christian-data

## Context

The repo at `raw/Commentaries-Database/` contains 58,675 TOML files, one per verse/passage reference, with quotes from 335+ Church Fathers and historical authors. The LICENSE file explicitly states PUBLIC DOMAIN with no restrictions.

### TOML Schema
Each file is named `{Book} {Chapter}_{Verse(s)}.toml` and contains:
```toml
[[commentary]]
quote = '''
Full quote text from the author...
'''
source_url = 'https://www.newadvent.org/fathers/2802.htm'
source_title = "On the Incarnation of the Word 10"
```

Multiple `[[commentary]]` blocks per file are common. The verse reference is encoded in the filename, not in the TOML content.

## Your Task

### Step 1: Map the dataset
- Count total TOML files
- List all unique author directories
- Count files per author (top 20)
- Map which Bible books are covered
- Document the filename format for verse ranges (e.g., `1_1-5.toml`)
- Check for any non-TOML files or unexpected structures

### Step 2: Build book name mapping
The filenames use full book names (e.g., "1 Corinthians"). Build a mapping to OSIS book codes:
- Gen, Exod, Lev, Num, Deut, Josh, Judg, Ruth, 1Sam, 2Sam, 1Kgs, 2Kgs, 1Chr, 2Chr, Ezra, Neh, Esth, Job, Ps, Prov, Eccl, Song, Isa, Jer, Lam, Ezek, Dan, Hos, Joel, Amos, Obad, Jonah, Mic, Nah, Hab, Zeph, Hag, Zech, Mal, Matt, Mark, Luke, John, Acts, Rom, 1Cor, 2Cor, Gal, Eph, Phil, Col, 1Thess, 2Thess, 1Tim, 2Tim, Titus, Phlm, Heb, Jas, 1Pet, 2Pet, 1John, 2John, 3John, Jude, Rev

Save the mapping as `scripts/osis_book_codes.json` for reuse across other categories.

### Step 3: Parse TOML → JSON
Write a Python script (`scripts/parse_commentaries_db.py`) that:
- Walks all author directories
- Parses each TOML file
- Extracts: author (from directory name), book + chapter + verse(s) (from filename), quote text, source URL, source title
- Outputs verse-keyed JSON to `processed/church_fathers/`
- Groups by author, then by book
- Handles verse ranges in filenames
- Uses `py -3` to run
- Uses only ASCII characters in print() output

### Step 4: Create manifest
Save to: `processed/church_fathers/MANIFEST.md`

Include:
- Total quotes processed
- Unique authors count
- Coverage by Bible book
- Top 20 authors by quote count
- Source commit hash: 6f92a8ce
- Any parsing errors or skipped files

## Constraints
- Do NOT modify the raw/ data
- Do NOT attempt to deduplicate quotes across verse references (save that for Phase 1 processing)
- Process ALL authors — we can filter later
```

---

### T1-3: bible_databases/BSB.json → Bible Text

```
You are processing the BSB.json Bible text (already cloned) into a structured dataset for the Open Christian Data project.

WORKING DIRECTORY: <repo-root>  # clone of OpenChristianData/open-christian-data

## Context

The repo at `raw/bible_databases/` (12GB total — do NOT run broad operations on the entire repo) contains BSB.json which has the Berean Standard Bible text for all 66 books. License: CC0 1.0.

## Your Task

### Step 1: Inspect BSB.json
- Read the first 100 lines to understand the JSON structure
- Document the schema (book, chapter, verse, text fields)
- Count total verses
- Confirm all 66 books are present
- Check for any unusual characters or formatting

### Step 2: Convert to our schema
Write a Python script (`scripts/parse_bsb.py`) that:
- Reads `raw/bible_databases/BSB.json`
- Outputs to `processed/bible_text/bsb/` — one JSON file per book using OSIS codes
- Each file: `{osis_code}.json` with structure: `{book, chapters: [{chapter, verses: [{verse, text}]}]}`
- Reuse OSIS mapping from `scripts/osis_book_codes.json` (create if not yet built by T1-2)
- Add provenance metadata: source, license (CC0), commit hash (a228a19a), processing date
- Uses `py -3` to run
- Uses only ASCII characters in print() output

### Step 3: Also inspect TSK cross-references
The TSK data is in `raw/bible_databases/formats/sqlite/extras/` as 7 SQLite files.
- List the 7 files and their sizes
- Open one and document the schema (table names, column names, sample rows)
- Count total cross-reference entries
- Document what a cross-reference entry looks like
- Do NOT process TSK yet — just document the schema for a future prompt

### Step 4: Create manifest
Save to: `processed/bible_text/MANIFEST.md`

Include: verse count per book, total verses, schema used, source commit hash, license.

## Constraints
- Do NOT process the full 12GB repo — only touch BSB.json and the extras/ directory
- Do NOT process other translations (most are copyrighted)
```

---

### T1-4: Standard Ebooks → Full Christian Catalog

```
You are cloning and processing confirmed public domain Christian texts from Standard Ebooks for the Open Christian Data project.

WORKING DIRECTORY: <repo-root>  # clone of OpenChristianData/open-christian-data

## Context

Standard Ebooks releases all editorial work as CC0 1.0. Underlying texts are US public domain. Source files are on GitHub as semantic XHTML (not epub binary) — better quality than Project Gutenberg plain text.

Source URL pattern: https://github.com/standardebooks/{se-identifier}
Text files are at: src/epub/text/ within each repo

## Target Titles

| SE Identifier | Category | Output Path |
|---|---|---|
| john-bunyan_the-pilgrims-progress | theological_work | processed/theological_works/ |
| augustine-of-hippo_the-city-of-god_marcus-dods_george-wilson_j-j-smith | theological_work | processed/theological_works/ |
| g-k-chesterton_orthodoxy | theological_work | processed/theological_works/ |
| g-k-chesterton_heretics | theological_work | processed/theological_works/ |
| g-k-chesterton_the-everlasting-man | theological_work | processed/theological_works/ |
| thomas-a-kempis_the-imitation-of-christ_william-benham | devotional | processed/devotionals/ |
| george-macdonald_unspoken-sermons | sermon | processed/sermons/macdonald/ |
| evelyn-underhill_practical-mysticism | devotional | processed/devotionals/ |
| archibald-alexander_a-day-at-a-time | devotional | processed/devotionals/ |
| john-milton_paradise-lost | theological_work | processed/theological_works/ |

NOTE: Do NOT download C.S. Lewis titles (Narnia, poetry) — published 1950-1956, NOT US public domain until ~2046-2051.
NOTE: Augustine's City of God (Marcus Dods translation) is preferred over the Project Gutenberg version — better markup.
NOTE: Imitation of Christ from SE replaces Project Gutenberg #26222 in T2-2 — remove that task or skip it.

## Your Task

### Step 1: Clone all repos
Clone each repo to `raw/standard_ebooks/{se-identifier}/`. Use HTTPS:
```bash
git clone https://github.com/standardebooks/{se-identifier}.git raw/standard_ebooks/{se-identifier}
```
Clone all 10 repos. No rate limit concern — GitHub static clone, not web scraping.

### Step 2: Inspect structure
For the first 2-3 repos:
- Locate the XHTML text files (src/epub/text/)
- Document which files contain main body text vs front/back matter
- Confirm the chapter/section structure
- Note any unusual structural patterns (e.g., Pilgrim's Progress has Part 1 + Part 2)

### Step 3: Write a shared XHTML extractor
Write a Python script (`scripts/parse_standard_ebooks.py`) that:
- Takes an SE identifier as argument
- Reads the XHTML source files from src/epub/text/
- Strips epub-specific markup (keeps paragraph text and headings)
- Preserves chapter/section structure
- Outputs structured JSON to the appropriate processed/ subdirectory
- Schema (theological_work): `{title, author, year, translator, license: "cc0", source_license: "cc0", source_url: "https://github.com/standardebooks/...", chapters: [{number, title, text}]}`
- Schema (sermon): `{title, author, series_number, license: "cc0", source_license: "cc0", source_url, text}`
- Schema (devotional): `{title, author, year, license: "cc0", source_license: "cc0", source_url, chapters: [{title, text}]}`
- Uses `py -3` to run
- Uses only ASCII characters in print() output

### Step 4: Process all 10 titles
Run the extractor on each title. Fix any per-title structural quirks (e.g., Pilgrim's Progress parts, Unspoken Sermons 3 series).

### Step 5: Create manifests
- `processed/theological_works/MANIFEST.md` — append SE entries
- `processed/devotionals/MANIFEST.md` — append SE entries
- `processed/sermons/MANIFEST.md` — create or append SE entries

Include: word counts, chapter counts, source repo commit hash, license (CC0), any parsing issues.

## Constraints
- Do NOT download or process Narnia or other C.S. Lewis fiction — not yet US public domain
- Do NOT use the epub binary files — use the XHTML source from the GitHub repo
- Imitation of Christ from SE supersedes Project Gutenberg #26222
```

---

### T1-5: JWBickel/BibleDictionaries → Reference Works

```
You are downloading and processing the JWBickel/BibleDictionaries dataset from HuggingFace for the Open Christian Data project.

WORKING DIRECTORY: <repo-root>  # clone of OpenChristianData/open-christian-data

## Respectful Downloading Standards (MANDATORY)
[Paste full standards block from preamble]

## Context

The HuggingFace dataset `JWBickel/BibleDictionaries` contains 4 reference works in JSONL format:
- Easton's Bible Dictionary (3,960 entries, 1893)
- Smith's Bible Dictionary (4,560 entries, 1863)
- Hitchcock's Bible Names Dictionary (2,620 entries)
- Torrey's Topical Textbook (623 entries)

Total: ~23,536 entries. Structure: `{"term": "...", "definitions": ["..."]}`. All underlying texts are public domain. The HuggingFace dataset has no explicit license — an email has been sent to JWBickel requesting clarification (Tier 3).

## Your Task

### Step 1: Download
Use the HuggingFace CLI or direct HTTP to download the JSONL files:
```bash
pip install huggingface_hub
```
Or use direct download URLs from the dataset page. Save raw files to `raw/bible_dictionaries/`.

### Step 2: Inspect
- Confirm entry counts per dictionary match expected (Easton=3960, Smith=4560, Hitchcock=2620, Torrey=623)
- Document actual JSONL structure with 3 sample entries per dictionary
- Check for any encoding issues or empty entries

### Step 3: Process
Write a Python script (`scripts/parse_bible_dictionaries.py`) that:
- Reads each JSONL file
- Outputs normalized JSON to `processed/reference/eastons.json`, `processed/reference/smiths.json`, etc.
- Schema per entry: `{term, definitions: [str], source_dictionary, source_year}`
- Add provenance metadata
- Uses `py -3` to run
- Uses only ASCII characters in print() output

### Step 4: Create manifest
Save to: `processed/reference/MANIFEST.md`

Include: entry counts per dictionary, total entries, sample entries, provenance, license status (PD text, HuggingFace license pending).
```

---

## Tier 2 — Simple Downloads (settled sources, clear licensing)

### T2-1: CrossWire SWORD → Commentaries & Devotionals

```
You are downloading and extracting SWORD modules from CrossWire for the Open Christian Data project.

WORKING DIRECTORY: <repo-root>  # clone of OpenChristianData/open-christian-data

## Respectful Downloading Standards (MANDATORY)
[Paste full standards block from preamble]

## Context — What We Know

From investigation (research/commentary/SOURCE_INVESTIGATION.md and research/devotional/SOURCE_INVESTIGATION.md):

### Commentary Modules (Public Domain, ZIP download)
| Module | Content | Install Size |
|--------|---------|-------------|
| `Barnes` | Barnes' Notes on the NT | 5.82 MB |
| `CalvinCommentaries` | Calvin's Commentaries (47 books — see coverage note) | 20.62 MB |
| `Wesley` | Wesley's Notes on the Bible (whole Bible) | Unknown |

### Devotional Modules (Public Domain, ZIP download)
| Module | Content | Entries |
|--------|---------|---------|
| `SME` | Spurgeon's Morning and Evening | 730 (AM + PM daily) |
| `Daily` | Daily Light on the Daily Path | 730 (AM + PM daily) |

### Download URLs
Module ZIP: `https://www.crosswire.org/sword/servlet/SwordMod.Verify?modName={name}&pkgType=raw`

### robots.txt
- Crawl-delay: 30 seconds
- `/ftpmirror/pub/sword/raw/modules/` is Disallowed (bulk FTP)
- The servlet URL above is NOT disallowed — it's the intended per-module download method

### Tooling
- **pysword** reads Bible modules ONLY — does NOT support commentaries or devotionals
- **diatheke** (part of libsword) reads ALL module types including devotionals
- Install via WSL: `sudo apt install sword-tools`
- Devotional key format: `mm.dd` (e.g., `01.15` for January 15)

### Calvin Coverage Note
Calvin's commentaries cover 47 books. He did NOT write commentaries on: Ruth, Judges, Samuel, Kings, Chronicles, Ezra, Nehemiah, Esther, Job, Proverbs, Ecclesiastes, Song of Solomon, Acts, Revelation. This is a source limitation, not a data gap.

## Your Task

### Step 1: Download modules (5 ZIPs, 30-second delay between requests)
Download each module ZIP to `raw/sword_modules/{module_name}.zip`:
1. Barnes
2. CalvinCommentaries
3. Wesley
4. SME
5. Daily

Use 30-second delay between requests (per robots.txt crawl-delay). SHA-256 hash each file. Log all requests.

### Step 2: Extract and inspect (commentary modules)
For Barnes, CalvinCommentaries, and Wesley:
- Unzip to `raw/sword_modules/{module_name}/`
- Document the internal file structure
- Try reading with pysword first — if it fails (likely for commentaries), document the error
- Attempt to read the raw binary files directly if pysword fails
- Document what format the text is in and what tools are needed

### Step 3: Extract devotional modules via diatheke (WSL)
For SME and Daily:
- Install sword-tools in WSL if not present: `sudo apt install sword-tools`
- Copy module files to WSL SWORD path
- Extract all 730 entries per module using diatheke:
  ```bash
  for month in $(seq -w 1 12); do
    for day in $(seq -w 1 31); do
      diatheke -b SME -k "$month.$day" 2>/dev/null
    done
  done
  ```
- Parse output into JSON: `{date: "MM-DD", period: "AM|PM", verse: "...", text: "..."}`
- Save to `processed/devotionals/morning_and_evening.json` and `processed/devotionals/daily_light.json`

### Step 4: Alternative extraction (if diatheke is not available)
If WSL/diatheke is not available:
- The SWORD rawld format stores data in `.dat`, `.idx` files
- Keys are encoded as `$$$mm.dd`
- Write a Python binary parser to read the rawld format directly
- Document whatever approach works

### Step 5: Create manifests
Commentary manifest: `processed/commentaries/sword/MANIFEST.md`
Devotional manifest: `processed/devotionals/MANIFEST.md`

Include: module versions, entry counts, coverage per Bible book (for commentaries), date coverage (for devotionals), source URLs, SHA-256 hashes.

## Constraints
- Do NOT download the `DBD` (Day By Day By Grace) module — modern author, likely copyrighted
- Do NOT download the Tyndale module from HelloAO — CC BY-SA, incompatible with CC0
```

---

### T2-2: Project Gutenberg → Catechisms, Theological Works, Devotional

```
You are downloading public domain texts from Project Gutenberg for the Open Christian Data project.

WORKING DIRECTORY: <repo-root>  # clone of OpenChristianData/open-christian-data

## Respectful Downloading Standards (MANDATORY)
[Paste full standards block from preamble]

## Context — What We Know

From investigations, these specific Project Gutenberg texts are confirmed available and public domain:

### Catechisms
| PG # | Title | Translation | Use For |
|------|-------|-------------|---------|
| 1670 | Luther's Small Catechism | Bente/Dau 1921 | Catechism dataset — nested part/section/Q&A structure |
| 1722 | Luther's Large Catechism | Bente/Dau 1921 | Treatise dataset — continuous prose, NOT Q&A |
| 14552 | Baltimore Catechism No. 2 | Original 1885 | Catechism dataset — canonical version, numbered Q&A |
| 14551 | Baltimore Catechism No. 1 | Original 1885 | First communion edition (simpler) |
| 14553 | Baltimore Catechism No. 3 | Original 1885 | Post-confirmation edition |

### Theological Works
| PG # | Title | Translation | Notes |
|------|-------|-------------|-------|
| 45001 | Calvin's Institutes Vol. 1 | Beveridge 1845 | 4 books, ~80 chapters |
| 64392 | Calvin's Institutes Vol. 2 | Beveridge 1845 | Continuation of above |
| 3296 | Augustine's Confessions | Pusey translation | 13 books — use THIS, not Outler |
| 45304 | Augustine's City of God Vol. 1 | Glasgow 1871/Dods | 22 books total |
| 45305 | Augustine's City of God Vol. 2 | Glasgow 1871/Dods | Continuation |

### Devotional
| PG # | Title | Notes |
|------|-------|-------|
| 26222 | The Imitation of Christ | Thomas a Kempis — 4 books with chapters, NOT date-keyed |

### Copyright Traps to Avoid
- Do NOT use CPH (Concordia Publishing House) translations of Luther — copyrighted
- Do NOT use the Outler translation of Augustine's Confessions — may be 20th century
- The Pusey translation (PG #3296) is safely PD

## Project Gutenberg Access Rules
- Use the robot harvest endpoint: `https://www.gutenberg.org/robot/harvest?filetypes[]=txt`
- Or direct UTF-8 text download: `https://www.gutenberg.org/ebooks/{id}.txt.utf-8`
- 2-second minimum delay between requests
- Use OCD User-Agent header
- Do NOT scrape the main site pages

## Your Task

### Step 1: Download all texts
Download UTF-8 plain text for each PG number above to `raw/gutenberg/pg{id}.txt`:
- 11 files total
- 2-second delay between requests
- SHA-256 hash each file
- Log all requests

### Step 2: Inspect and document
For each downloaded text:
- Note the Project Gutenberg header/footer markers (these must be stripped)
- Document the internal structure (chapters, sections, Q&A boundaries)
- Note any encoding issues

### Step 3: Parse catechisms
Write a Python script (`scripts/parse_gutenberg_catechisms.py`) that:
- Strips PG headers/footers
- Parses Luther's Small Catechism into part/section/Q&A structure
- Parses Luther's Large Catechism into part/chapter/paragraph structure (NOT Q&A)
- Parses Baltimore Catechisms into numbered Q&A
- Outputs to `processed/catechisms/`
- Uses `py -3` to run
- Uses only ASCII characters in print() output

### Step 4: Parse theological works
Write a Python script (`scripts/parse_gutenberg_theology.py`) that:
- Strips PG headers/footers
- Parses Calvin's Institutes into book/chapter structure
- Parses Augustine's Confessions into book/chapter structure
- Parses Augustine's City of God into book/chapter structure
- Parses Imitation of Christ into book/chapter structure
- Outputs to `processed/theological_works/`
- Schema: `{title, author, year, translation, translation_year, license, books: [{number, title, chapters: [{number, title, text}]}]}`

### Step 5: Create manifests
- `processed/catechisms/MANIFEST.md` — append to existing if present
- `processed/theological_works/MANIFEST.md` — append to existing if present

Include: PG numbers, word counts, chapter counts, translation details, any parsing issues.
```

---

### T2-3: BCP 1662 & 1928 → Prayer Texts

```
You are downloading the Book of Common Prayer (1662 and 1928 US editions) for the Open Christian Data project.

WORKING DIRECTORY: <repo-root>  # clone of OpenChristianData/open-christian-data

## Respectful Downloading Standards (MANDATORY)
[Paste full standards block from preamble]

## Context — What We Know

From investigation (research/prayer/SOURCE_INVESTIGATION.md):

### BCP 1662
- **Best source:** eskimo.com/~lhowell/bcp1662/ — HTML + RTF + ASCII, collects structured by occasion
- **Download page:** eskimo.com/~lhowell/bcp1662/download/index.html
- **License:** Public domain in the US. UK Crown copyright exists but does not affect a US-based project.
- **robots.txt:** No restrictions found. Site has been live 20+ years.

### BCP 1928 (US)
- **Best source:** justus.anglican.org/resources/bcp/1928/BCP_1928.htm
- **License:** Confirmed public domain by Church Publishing Inc. (Episcopal Church publisher)
- **robots.txt:** 10-second crawl delay for all agents

### Also grab
- **Didache** — Wikisource API: `https://en.wikisource.org/w/api.php?action=parse&page=Didache&prop=wikitext&format=json`
  - Chapters 9-10 = Eucharistic prayer; Chapter 8 = Lord's Prayer instruction
  - Use Kirsopp Lake (1912) translation — public domain

## Your Task

### Step 1: Download BCP 1662
- Download the ASCII/RTF version from the eskimo.com download page
- Save to `raw/bcp1662/`
- SHA-256 hash all files
- Document the file structure

### Step 2: Download BCP 1928
- Download `http://justus.anglican.org/resources/bcp/1928/BCP_1928.htm`
- Use 10-second delay (per robots.txt crawl-delay)
- Save to `raw/bcp1928/`
- SHA-256 hash

### Step 3: Download Didache
- Single Wikisource API call for the page content
- Save raw response to `raw/wikisource/didache.json`

### Step 4: Parse BCP 1662 collects
Write a Python script (`scripts/parse_bcp1662.py`) that:
- Reads the ASCII/RTF source
- Extracts individual collects with their occasion labels (Advent 1, Christmas, Epiphany, etc.)
- Expected output: ~120 discrete prayers with title, occasion, and source metadata
- Outputs to `processed/prayers/bcp1662_collects.json`
- Schema: `{title, source, year: 1662, license: "PD", prayers: [{title, occasion, text, scripture_refs: []}]}`
- Uses `py -3` to run
- Uses only ASCII characters in print() output

### Step 5: Parse Didache prayers
Write a Python script (`scripts/parse_didache.py`) that:
- Extracts chapters 8-10 (prayer content)
- Outputs to `processed/prayers/didache_prayers.json`

### Step 6: Create manifest
Save to: `processed/prayers/MANIFEST.md`

Include: collect count (BCP 1662), prayer count (Didache), source URLs, download dates, hashes.

## Constraints
- BCP 1928 from justus.anglican.org: use 10-second delay, not 2-second
- Do NOT attempt the 1940 Scottish Book of Common Order — copyright uncertain
```

---

### T2-4: navestopicalbible.org → Nave's Topical Bible

```
You are downloading and parsing Nave's Topical Bible from navestopicalbible.org for the Open Christian Data project.

WORKING DIRECTORY: <repo-root>  # clone of OpenChristianData/open-christian-data

## Respectful Downloading Standards (MANDATORY)
[Paste full standards block from preamble]

## Context — What We Know

From investigation (research/reference/SOURCE_INVESTIGATION.md):

- **Source:** navestopicalbible.org — purpose-built developer download with 20,000+ topics
- **License:** Underlying text is public domain (Nave's Topical Bible, 1896). Site explicitly provides the download for developer use.
- **Format:** Custom plain-text markup, files delivered in batches of 50 topics
- **Data quality:** >99% clean (passed systematic error-pattern checking)
- **robots.txt:** Check before downloading — site has not restricted crawlers as of investigation
- **No HuggingFace equivalent exists** — this will be the first structured Nave's dataset on the platform

### Custom Markup Format
```
$$topic_number
\TOPIC NAME\
# Verse.Reference.Here
# Another.Verse.Reference
» 1234
|
```

Where:
- `$$N` — integer topic ID
- `\TOPIC NAME\` — topic heading (surrounded by backslashes)
- `# verse` — verse reference in this topic (may be multiple lines)
- `»` (or `>>`) — cross-reference to another topic number
- `|` — terminates the topic entry
- Some entries may have `$$N (n/a)` indicating an unresolvable reference

Format is documented in a README within the download itself.

### Other Sources (for validation only, do NOT use as primary)
- **MetaV (GitHub)**: CSV with Topics + TopicIndex tables. Nave's and Torrey's topics are merged with no distinguishing flag — use only for cross-checking verse coverage counts.
- **CCEL ThML**: Will be used for authoritative validation once EMAIL-2 permission arrives.

## Your Task

### Step 1: Check robots.txt and download page
- Fetch robots.txt from navestopicalbible.org
- Navigate to the developer download section
- Document the exact download method (single ZIP? multiple files? API?)
- Note any terms or attribution requests on the download page

### Step 2: Download the full dataset
- Download all topic files to `raw/naves_topical/`
- SHA-256 hash all downloaded files
- Log all requests
- If files are delivered in batches of 50 topics: download all batches, respect any crawl delay

### Step 3: Read the format documentation
- Read the README or format spec included in the download
- Document any format conventions not listed above
- Note any edge cases or exceptions

### Step 4: Write the parser
Write a Python script (`scripts/parse_naves_topical.py`) that:
- Reads all downloaded topic files
- Parses each topic entry using the custom markup
- Outputs to `processed/reference/naves_topical.jsonl` (one JSON object per line)
- Schema per record:
  ```json
  {
    "topic_id": 1234,
    "topic_name": "AARON",
    "verse_refs": ["Exod.4.14", "Exod.6.20"],
    "cross_refs": [567, 890],
    "source_license": "public_domain",
    "source_url": "https://navestopicalbible.org/...",
    "translation_year": null
  }
  ```
- Normalise verse references to OSIS format where possible (reuse scripts/osis_book_codes.json)
- Handle `(n/a)` unresolvable references — include as null in cross_refs with a note
- Count and report any malformed entries

### Step 5: Validate against MetaV
- Clone the MetaV reference repo: `https://github.com/robertrouse/KJV-bible-database-with-metadata-MetaV-`
- Load the TopicIndex CSV
- Compare: topic counts, verse coverage per topic
- Document any topics in MetaV not found in our parse (or vice versa)
- Note: MetaV merges Nave's + Torrey's — count mismatches are expected

### Step 6: Create manifest
Save to: `processed/reference/MANIFEST.md` (create or append)

Include:
- Total topics parsed
- Total verse references
- Total cross-references
- Any malformed entries and their topic IDs
- MetaV comparison results
- Source URL, download date, SHA-256 hash of downloaded files
- Note: CCEL ThML validation pending EMAIL-2 reply

## Constraints
- Primary source is navestopicalbible.org — do NOT use MetaV as primary text source
- Do NOT scrape CCEL for Nave's — permission email pending
- Note any attribution preferences stated on the download page and record them in the manifest
```

---

## Tier 3 — Emails (highest leverage per token spent)

These are not prompts — they are draft emails to send from openchristiandata@gmail.com.

### EMAIL-1: Hymnary.org — Research Data Access

```
To: https://hymnary.org/info/email.html?to=feedback
From: openchristiandata@gmail.com
Subject: Research data access request — Open Christian Data project

Dear Hymnary.org team,

I'm building Open Christian Data (github.com/openchristiandata), an open-source project creating structured, machine-readable datasets from public domain Christian literature for researchers, developers, and churches. We're publishing on HuggingFace — no existing hymn lyric corpus exists there.

To be clear upfront: this is not a copyright permission request. I understand Hymnary.org does not grant copyright permission and that CCLI, OneLicense, and similar agencies handle licensing for copyrighted works. We are exclusively interested in hymn texts that are already in the public domain (pre-1928 US publication, expired copyright).

Hymnary.org is uniquely positioned as the most comprehensive hymn database in existence, and your NEH-funded mission to serve scholars aligns closely with what we're doing.

I'd like to ask:

1. Would you be willing to share a CSV or data export of public domain hymn texts with metadata (title, author, year, metre, tune name, scripture references, source hymnal)? Again — only texts where the lyrics are clearly public domain.

2. Does your full database include complete stanza text for these older hymns, or primarily first-line indexing?

3. What are your preferences for how we credit Hymnary.org in the published dataset?

We're happy to work within whatever terms you set. The project is non-commercial, and all published datasets will be freely available.

Thank you for the work you do preserving this heritage.

Best regards,
Open Christian Data
openchristiandata@gmail.com
github.com/openchristiandata
```

---

### EMAIL-2: CCEL — ThML/XML Permission

```
To: [Contact form at ccel.org]
From: openchristiandata@gmail.com
Subject: Permission request — ThML/XML use in open-source data project

Dear CCEL team,

I'm building Open Christian Data (github.com/openchristiandata), an open-source project creating structured, machine-readable datasets from public domain Christian literature. We're publishing on HuggingFace for researchers, developers, and churches.

CCEL's ThML files are the richest structured source for many works we'd like to include — Calvin's Institutes, Hodge's Systematic Theology, Edwards' treatises, Owen, Baxter, Athanasius, Nave's Topical Bible, Wesley's sermons, and others. The underlying texts are all public domain.

Your copyright policy states that CCEL editions may be used for "personal, educational, or non-profit purposes." Our project is non-commercial and open-source, but I want to confirm explicitly before proceeding:

1. May we use your ThML/XML files as a source for parsing public domain text into our structured datasets?

2. How would you like CCEL to be credited in the published datasets?

3. Are there any specific works or formats you'd prefer we not use?

We will always credit CCEL as the source of the digital text and link back to your editions. We're building on the tremendous work CCEL has done making these texts accessible.

Thank you for your stewardship of this library.

Best regards,
Open Christian Data
openchristiandata@gmail.com
github.com/openchristiandata
```

---

### EMAIL-3: Yale Edwards Center — Data Partnership

```
To: [edwards.yale.edu contact]
From: openchristiandata@gmail.com
Subject: Data partnership inquiry — Jonathan Edwards sermon transcripts

Dear Edwards Center team,

I'm building Open Christian Data (github.com/openchristiandata), an open-source project creating structured, machine-readable datasets from public domain Christian literature for researchers, developers, and churches.

The Works of Jonathan Edwards Online is an extraordinary scholarly resource. Edwards' sermons are all public domain (18th century), and we'd love to include them in our sermon corpus — which would be the first structured, machine-readable public domain sermon dataset at this scale.

We currently have access to a handful of Edwards' major treatises via CCEL (Religious Affections, Freedom of the Will), but the WJE Online contains 1,200+ sermon transcripts that don't exist in structured digital form elsewhere.

Would you be open to discussing:

1. Whether bulk access to the sermon transcripts is possible for an open-data research project?

2. Whether there's a preferred format or API for accessing the transcripts?

3. Any attribution or terms you'd require?

We're happy to work within whatever framework serves your mission. All published datasets will be freely available and will credit the Edwards Center prominently.

Best regards,
Open Christian Data
openchristiandata@gmail.com
github.com/openchristiandata
```

---

### EMAIL-4: JWBickel — HuggingFace License Confirmation

```
To: [HuggingFace message or GitHub contact for JWBickel]
From: openchristiandata@gmail.com
Subject: License for BibleDictionaries HuggingFace dataset

Hi,

I'm building Open Christian Data (github.com/openchristiandata), an open-source project creating structured datasets from public domain Christian literature. Your BibleDictionaries dataset on HuggingFace (Easton's, Smith's, Hitchcock's, Torrey's) is exactly the kind of clean, structured data we'd love to build on.

The underlying texts are all public domain, but I noticed the dataset doesn't have an explicit license in its metadata. Would you be willing to add a CC0 or public domain dedication to the dataset? This would make it clear for downstream users.

Either way, thank you for putting this together — it's well structured and useful.

Best regards,
Open Christian Data
openchristiandata@gmail.com
```

---

## Tier 4 — Longer Downloads (rate-limited, need scripts)

### T4-1: HelloAO CLI Self-Host → 5 Commentaries (replaces old DL-1)

```
You are setting up the HelloAO CLI to self-host and generate static JSON commentary files for the Open Christian Data project.

WORKING DIRECTORY: <repo-root>  # clone of OpenChristianData/open-christian-data

## IMPORTANT — DO NOT USE THE API DIRECTLY

HelloAO's documentation explicitly states: "Do not use the API to download an entire commentary." The correct approach is:
1. Clone the HelloAO bible-api repo (MIT license)
2. Install @helloao/cli
3. Self-host to generate static JSON files locally

This avoids all rate limit concerns and respects the project's wishes.

## Commentaries Available (PDM 1.0 — Public Domain Mark)
| ID | Commentary | Coverage |
|----|-----------|----------|
| matthew-henry | Matthew Henry Complete | 65 books |
| jfb | Jamieson-Fausset-Brown | 66 books |
| gill | John Gill's Exposition | 66 books |
| adam-clarke | Adam Clarke's Commentary | 57 books |
| keil-delitzsch | Keil & Delitzsch OT | 39 books (OT only) |

EXCLUDE: `tyndale` — CC BY-SA 4.0 (copyleft, incompatible with CC0 target)

## Your Task

### Step 1: Clone the repo
```bash
git clone https://github.com/HelloAOLab/bible-api.git raw/helloao-bible-api
```

### Step 2: Inspect the CLI
- Read the README and any CLI documentation
- Understand how `@helloao/cli` generates static files
- Document the exact commands needed
- Check Node.js version requirements

### Step 3: Install and generate
- Install Node.js dependencies
- Run the CLI to generate static JSON for all 5 PD commentaries
- Save output to `raw/helloao/{commentary_id}/`
- Document the JSON structure of generated files

### Step 4: Verify coverage
For each commentary:
- Count total files/chapters generated
- Compare against expected book counts (above)
- Document any gaps
- Check JSON structure matches what the API serves

### Step 5: Create manifest
Save to: `raw/helloao/DOWNLOAD_MANIFEST.md`

Include: commentary list, file counts, coverage matrix, total data size, JSON schema sample, generation date, source repo commit hash.

## Constraints
- Do NOT make any requests to bible.helloao.org API
- This is entirely local — clone repo, run CLI, generate files
- If the CLI approach doesn't work (e.g., CLI is deprecated or broken), document what happened and fall back to contacting HelloAO for guidance
```

---

### T4-2: The Kingdom Collective → Spurgeon Sermons (~3,000)

```
You are downloading Spurgeon's sermon texts from The Kingdom Collective for the Open Christian Data project.

WORKING DIRECTORY: <repo-root>  # clone of OpenChristianData/open-christian-data

## Respectful Downloading Standards (MANDATORY)
[Paste full standards block from preamble]

## Context — What We Know

From investigation (research/sermon/SOURCE_INVESTIGATION.md):

- **Source:** thekingdomcollective.com/spurgeon/sermon/[N]/
- **Content:** ~3,000 of Spurgeon's 3,563 sermons as HTML pages
- **Origin:** Text extracted from SpurgeonGems PDFs by Emmett O'Donnell, parsed into HTML by Benry Yip
- **robots.txt:** Returns 404 — no robots.txt file exists
- **ToS:** No ToS page found
- **Site status:** Appears dormant since 2014, hosted on Netlify, pages still live
- **Quality:** Some parsing artifacts from PDF extraction (mis-parsed headers, spelling errors). Far better than re-OCR'ing Victorian print scans.
- **Copyright:** Spurgeon died 1892. All texts public domain.
- **GitHub repo:** `bjcy/tcs.sc` is 404 (deleted). The website is the only accessible version.
- **No existing dataset:** No Spurgeon sermon corpus exists on HuggingFace or GitHub.

## Your Task

### Step 1: Test access
- Fetch sermon #1, #100, #1000, #3000 to confirm pattern and availability
- Document the HTML structure of a sermon page (title, scripture reference, body text)
- Note the highest sermon number that returns content

### Step 2: Build the scraper
Write a Python script (`scripts/scrape_spurgeon_sermons.py`) that:
- Iterates through sermon numbers 1 to 3563
- Fetches each page with 2-second delay
- User-Agent: `OpenChristianData/1.0 (research; open-source data project; contact: openchristiandata@gmail.com)`
- Extracts: sermon number, title, scripture reference, full text
- Handles 404s gracefully (expected for ~500 sermons not in the collection)
- Saves raw HTML to `raw/spurgeon_sermons/html/{N}.html`
- Saves parsed JSON to `raw/spurgeon_sermons/json/{N}.json`
- Logs all requests to `research/sermon/request_log.csv`
- SHA-256 hashes each downloaded file
- Skips already-downloaded files (resume capability)
- Uses `py -3` to run
- Uses only ASCII characters in print() output

### Step 3: Run the scraper
- This will take several hours (3,563 URLs x 2-second delay = ~2 hours minimum)
- Run in background if possible
- Monitor for rate limiting or errors

### Step 4: Create manifest
Save to: `raw/spurgeon_sermons/DOWNLOAD_MANIFEST.md`

Include:
- Total sermons downloaded
- Total 404s (sermons not in collection)
- Date range of sermons (if extractable from metadata)
- Scripture reference coverage
- Sample JSON structure
- Any quality issues noted
- Total data size
```

---

### T4-3: CCEL → Wesley Sermons XML

```
You are downloading Wesley's sermon collection from CCEL for the Open Christian Data project.

WORKING DIRECTORY: <repo-root>  # clone of OpenChristianData/open-christian-data

## Respectful Downloading Standards (MANDATORY)
[Paste full standards block from preamble]

## Context — What We Know

From investigation (research/sermon/SOURCE_INVESTIGATION.md):
- CCEL has Wesley's sermons at `ccel.org/ccel/wesley/sermons.xml`
- 141 sermons across 5 series
- ThML/XML format with structured markup
- CCEL robots.txt: all crawlers permitted, 10-second crawl delay
- CCEL asserts copyright on formatting — email sent (EMAIL-2). For now, proceed with download; we'll verify permission before publishing.

Also available:
- Whitefield's sermons: check `ccel.org/ccel/whitefield/sermons.xml`
- Maclaren: multiple volumes — check `ccel.org/ccel/maclaren/`

## Your Task

### Step 1: Download Wesley sermons XML
- Fetch `https://www.ccel.org/ccel/wesley/sermons.xml`
- Use 10-second delay (CCEL crawl-delay)
- Save to `raw/ccel/wesley_sermons.xml`
- SHA-256 hash
- Log request

### Step 2: Check for Whitefield XML
- Try `https://www.ccel.org/ccel/whitefield/sermons.xml`
- If available, download with 10-second delay
- Save to `raw/ccel/whitefield_sermons.xml`

### Step 3: Inspect XML structure
- Document the ThML structure: `<div1>`, `<div2>`, `<div3>` hierarchy
- Count sermons
- Check for: title, scripture reference, sermon number, body text
- Note any `<scripRef>` tags (inline scripture references)

### Step 4: Parse Wesley XML
Write a Python script (`scripts/parse_ccel_sermons.py`) that:
- Reads the ThML XML
- Extracts each sermon: number, title, scripture text, body
- Outputs to `processed/sermons/wesley/`
- Schema: `{title, author, number, scripture_ref, text, source: "CCEL", source_url}`
- Handles ThML-specific markup (strip or convert `<scripRef>` tags)
- Uses `py -3` to run
- Uses only ASCII characters in print() output

### Step 5: Create manifest
Save to: `processed/sermons/MANIFEST.md`

Include: sermon counts, Wesley coverage, Whitefield availability, ThML structure notes, CCEL licensing status.

## Constraints
- 10-second delay between ALL CCEL requests
- If CCEL returns errors, back off to 30 seconds
- Do NOT spider CCEL — only fetch the specific URLs listed above
```

---

### T4-4: Project Gutenberg → Maclaren & Whitefield Sermons

```
You are downloading sermon collections from Project Gutenberg for the Open Christian Data project.

WORKING DIRECTORY: <repo-root>  # clone of OpenChristianData/open-christian-data

## Respectful Downloading Standards (MANDATORY)
[Paste full standards block from preamble]

## Context — What We Know

From investigation (research/sermon/SOURCE_INVESTIGATION.md):

### Alexander Maclaren — Expositions of Holy Scripture
- 17+ volumes on Project Gutenberg as clean HTML/text
- One of the easiest ingestions — well-structured, pre-digitized text
- Public domain (Maclaren died 1910)

### George Whitefield — Works
- 6-volume set on Project Gutenberg (sermons, letters, journals)
- ~75 sermons across the volumes
- Public domain (Whitefield died 1770)

## Your Task

### Step 1: Search and catalog
- Search Project Gutenberg for "Maclaren Expositions" — catalog all volume PG numbers
- Search for "Whitefield" — catalog all relevant PG numbers
- Document each volume: PG number, title, book of the Bible covered (for Maclaren)
- Use 2-second delay between search requests

### Step 2: Download all texts
- Download UTF-8 plain text for each PG number
- Save to `raw/gutenberg/sermons/maclaren/pg{id}.txt` and `raw/gutenberg/sermons/whitefield/pg{id}.txt`
- 2-second delay between requests
- SHA-256 hash each file
- Log all requests

### Step 3: Parse Maclaren
Write a Python script (`scripts/parse_maclaren.py`) that:
- Strips PG headers/footers
- Extracts individual sermons/expositions from each volume
- Identifies: title, scripture passage, body text
- Outputs to `processed/sermons/maclaren/`
- Uses `py -3` to run
- Uses only ASCII characters in print() output

### Step 4: Parse Whitefield
Write a Python script (`scripts/parse_whitefield.py`) that:
- Strips PG headers/footers
- Extracts sermons (separate from letters and journals)
- Identifies: title, scripture passage, body text
- Outputs to `processed/sermons/whitefield/`

### Step 5: Create manifest
Append to: `processed/sermons/MANIFEST.md`

Include: volume list, sermon counts per volume, total word counts, scripture coverage, PG numbers, any parsing issues.
```

---

## DL-1: HelloAO Commentary Download (REPLACED)

**This prompt has been replaced by T4-1 above.** The original DL-1 scripted direct API calls with 2-second delays. Investigation found that HelloAO's docs explicitly prohibit bulk API downloads. The correct approach (T4-1) uses `@helloao/cli` to self-host and generate static JSON locally.

---

## DL-2: GitHub Repository Clones (COMPLETED)

All 6 repositories have been cloned and inspected. See `raw/INVENTORY.md` for the master record and individual `INSPECTION_REPORT.md` files in each repo directory.

---

## Future Prompts (not yet drafted)

These will be drafted after Tier 3 emails receive responses:

| Prompt | Trigger | What It Does |
|--------|---------|-------------|
| T3-R1: Hymnary Ingest | Hymnary.org replies with CSV dump | Parse hymn CSV into structured JSON |
| T3-R2: CCEL ThML Download | CCEL grants permission | Download ThML for Hodge, Nave's, Edwards, Owen, Baxter, Athanasius |
| T3-R3: Yale Edwards Ingest | Yale provides bulk access | Parse Edwards sermon transcripts |
| T5-1: Internet Archive OCR | OCR pipeline ready | Spurgeon Treasury of David, Bengel, Lange |
| T5-2: ISBE Processing | OCR pipeline ready | 5-volume OCR project |
| T5-3: Puritan Prayers | Manual extraction | Owen Vol.4, Watson, Doddridge prayer texts |
| T5-4: Wikisource Confessions | Gap-fill needed | Confessional documents not in Creeds.json |

---

*This file was rewritten on 2026-03-27 after completing 8 source investigations and 6 GitHub repo inspections. All investigation reports are in `research/{category}/SOURCE_INVESTIGATION.md`. The synthesis of findings is in `research/SYNTHESIS.md`.*
