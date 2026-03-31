# OCD Project Journal

Permanent historical record. Newest entries at top. Never trimmed.

---

## 2026-03-31 — Nave's Topical Bible (CrossWire SWORD)

**Branch:** main
**What we worked on:** End-to-end pipeline for Nave's Topical Bible from CrossWire SWORD zLD module — binary format reverse-engineering, unit tests, parser, validation, README.

**What was completed:**
- `research/reference/request_log.csv` — download log for Nave.zip (SHA-256 recorded)
- `build/scripts/inspect_sword_zld.py` — probes zLD binary format (zdx/zdt), revealed 5,322 entries and TEI XML content
- `tests/test_naves_osis.py` — 20 unit tests: `extract_osis_refs`, `extract_cross_refs`, `parse_subtopics`, `slugify`
- `build/parsers/naves_topical.py` — full parser; `_decode_zld()` + `get_entry_from_block()` + `parse_subtopics()` + `extract_osis_refs()` + `extract_cross_refs()`; CLI `--dry-run` + `--limit N`
- `data/topical-reference/naves/naves-topical-bible.json` — 5,322 entries, 76,957 scripture refs, 12,343 KB
- `build/validate.py` — relaxed: empty subtopics is WARNING (not error) when `related_topics` non-empty (handles redirect-only entries)
- `README.md` — status table row, data directory listing, pipeline commands, source attribution

**Key discoveries:**
- OSIS refs pre-computed in TEI XML attributes — no book abbreviation lookup needed
- `eoff` in block internal index is entry size (not offset); cumulative sum gives position
- 2 redirect-only entries (SHOMER, TRADE): empty subtopics + non-empty related_topics — validator relaxed
- `data_start` guard formula corrected: correct value is `4 + count*8 = 244` (last entry's esz slot overlaps data start); prior formula `8 + count*8 = 248` fired as false warning on every valid block

**Post-session evaluation improvements (same session, /evaluate cycle):**
- `build/parsers/naves_topical.py` — guard formula fixed (`8+count*8` → `4+count*8`); block layout docstring updated with overlap explanation
- `plans/2026-03-30-naves-topical-parser.md` — Format Discovery section appended (TEI XML vs plain text, block index overlap, eoff semantics, redirect entries)
- `data/authors/registry.json` — removed duplicate orville-j-nave entry (richer pre-existing entry preserved)
- `00 CONTEXT/LESSONS.md` — added: "A check that fires on 100% of valid inputs means your model of the invariant is wrong, not that the data is noisy"

**Validation:** `py -3 build/validate.py --all` → **0 errors**, 150 warnings, 899 files.

**Commits:** 84fc952 (download), e849125 (inspect), 1901802 (tests), 22f7f78 + 5f6e708 (parser), 030f289 (data + validate), b68aa3a (README), cb1ad37 (LAST_SESSION), 026bdf6 (guard fix + plan doc + registry dedup)

**Where we stopped:** All work committed. Working tree clean.

---

## 2026-03-31 — Registry: Church Fathers (317 missing authors)

### What was done

Extended `data/authors/registry.json` from 40 to 357 entries by adding all
317 church fathers authors that were producing "Author not in registry" warnings
from the validator.

**Scripts written:**
- `build/scripts/extend_author_registry.py` — adds 317 entries, idempotent
- `build/scripts/patch_author_registry.py` — 17 sourced corrections from
  external verification pass (Wikipedia, Britannica, CCEL, OrthodoxWiki)

**Corrections applied during verification:**
- `andreas-of-caesarea` — dates cleared to null (637 unsupported)
- `arethas-of-caesarea` — death year 935 -> 939
- `theophylact-of-ohrid` — death year 1126 -> null (unsupported)
- `haimo-of-auxerre` — birth year 840 -> null (fabricated)
- `walafrid-strabo` — removed false attribution of Glossa Ordinaria to him
- `agapius-of-hierapolis` — tradition ["patristic"] -> ["orthodox"] (10th-c. Melkite, post-schism)
- `severus-of-antioch`, `jacob-of-edessa`, `cosmas-of-maiuma`, `abba-poemen`,
  `isaac-of-nineveh` — removed "orthodox" (all pre-1054; no strong exception)
- `john-wesley` — added "wesleyan" and "anglican" to tradition
- `cs-lewis` — nationality "British" -> "Irish" (self-identified)
- `gk-chesterton` — display_name corrected to "G. K. Chesterton"; "GK Chesterton"
  demoted to alias (to match structured-text data files)

**Pre-1054 "strong reason" exceptions kept as ["patristic", "orthodox"]:**
John Damascene, Maximus the Confessor, Andrew of Crete, Romanos the Melodist,
Sophronius of Jerusalem, Photios I, Desert Fathers.

### Final state

`py -3 build/validate.py --all` -- 0 errors, 163 warnings.

Remaining warnings:
- ~150 x "missing source_title" completeness warnings (pre-existing, across many datasets)
- 13 x "Author not in registry" from non-church-fathers datasets

### Next session prompt

Prompt ready in:
`02 PERSONAL/Open Christian Data/READY_TO_PASTE_PROMPTS.md`
-- "Registry: Non-Church-Fathers authors (13 missing + source_title gaps)"
